"""Tests for `gate.state.intake_cli`.

Focus is on the payload shape (what the workflow consumes) and on the
Markdown comment rendering. Heavy validation logic is already covered by
test_intake.py.
"""

from __future__ import annotations

import json
import textwrap

from gate.state import intake_cli

VALID_BODY = textwrap.dedent(
    """\
    ---
    choir-task-version: 1
    type: prove
    target_file: MyProj/Foo.lean
    target_decl: MyProj.Foo.add_comm
    project_ref:
      repo: org/myproj
      commit: 1a2b3c4d
      toolchain: leanprover/lean4:v4.x.y
    deps: [12]
    blueprint_ref: blueprint/foo.tex#add_comm
    ---

    ## Statement
    theorem MyProj.Foo.add_comm ...
    """
)

def test_build_payload_success() -> None:
    payload = intake_cli.build_payload(VALID_BODY, repo="org/myproj")
    assert payload["status"] == "ok"
    assert "task accepted" in payload["comment"]
    assert "MyProj.Foo.add_comm" in payload["comment"]
    assert "#12" in payload["comment"]
    assert "choir/available" in payload["add_labels"]
    assert "choir/type:prove" in payload["add_labels"]
    assert "choir/task" in payload["add_labels"]
    assert "choir/invalid" in payload["remove_labels"]
    assert "errors" not in payload


def test_build_payload_golf_task_accepted() -> None:
    # `type: golf` rides the generic non-review intake branch. Pinned
    # because the golf playbook relies on it (spec 2026-07-18).
    payload = intake_cli.build_payload(
        VALID_BODY.replace("type: prove", "type: golf"), repo="org/myproj"
    )
    assert payload["status"] == "ok"
    assert "choir/type:golf" in payload["add_labels"]
    assert "choir/available" in payload["add_labels"]


def test_build_payload_error() -> None:
    # Missing required field.
    body = VALID_BODY.replace("type: prove\n", "")
    payload = intake_cli.build_payload(body, repo="org/myproj")
    assert payload["status"] == "error"
    assert "rejected" in payload["comment"].lower()
    assert "choir/invalid" in payload["add_labels"]
    assert "choir/available" in payload["remove_labels"]
    assert "errors" in payload
    assert any(e["code"] == "missing_field" for e in payload["errors"])
    assert any(e["field"] == "type" for e in payload["errors"])


def test_build_payload_repo_mismatch() -> None:
    payload = intake_cli.build_payload(VALID_BODY, repo="other-org/different-repo")
    assert payload["status"] == "error"
    assert any(e["code"] == "repo_mismatch" for e in payload["errors"])


def test_main_writes_json_to_stdout(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    body_file = tmp_path / "body.txt"
    body_file.write_text(VALID_BODY, encoding="utf-8")
    rc = intake_cli.main(["--body-file", str(body_file), "--repo", "org/myproj"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "ok"


def test_main_handles_error_body(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    body_file = tmp_path / "body.txt"
    body_file.write_text("not even a YAML front-matter here\n", encoding="utf-8")
    rc = intake_cli.main(["--body-file", str(body_file), "--repo", "org/myproj"])
    # Exits 0 even on parse errors — the *workflow* uses the JSON to decide
    # what to do. The CLI's job is to report, not to fail.
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert any(e["code"] == "no_frontmatter" for e in payload["errors"])


# ---------------------------------------------------------------------------
# Idempotency (record_hash + existing_hashes + should_post_comment)
# ---------------------------------------------------------------------------


def test_re_intake_with_same_record_should_skip() -> None:
    first = intake_cli.build_payload(VALID_BODY, repo="org/myproj")
    h = first["record_hash"]
    # Simulate the prior comment appearing in the issue history.
    existing = [first["comment"]]
    second = intake_cli.build_payload(
        VALID_BODY, repo="org/myproj", existing_comments=existing
    )
    assert second["record_hash"] == h
    assert second["should_post_comment"] is False


def test_re_intake_with_changed_record_should_post() -> None:
    first = intake_cli.build_payload(VALID_BODY, repo="org/myproj")
    existing = [first["comment"]]
    # Change target_decl — different canonical record → different hash.
    changed = VALID_BODY.replace(
        "target_decl: MyProj.Foo.add_comm",
        "target_decl: MyProj.Foo.add_assoc",
    )
    second = intake_cli.build_payload(
        changed, repo="org/myproj", existing_comments=existing
    )
    assert second["record_hash"] != first["record_hash"]
    assert second["should_post_comment"] is True


def test_hash_is_stable_under_prose_changes() -> None:
    # The prose after the front-matter doesn't affect the canonical record,
    # so the hash must not change. This is the load-bearing property for
    # idempotency on issues.edited.
    h1 = intake_cli.build_payload(VALID_BODY, repo="org/myproj")["record_hash"]
    body_with_more_prose = VALID_BODY + "\n\n## Notes\n\nExtra context here.\n"
    h2 = intake_cli.build_payload(body_with_more_prose, repo="org/myproj")[
        "record_hash"
    ]
    assert h1 == h2


def test_unrelated_existing_comments_dont_match() -> None:
    payload = intake_cli.build_payload(
        VALID_BODY,
        repo="org/myproj",
        existing_comments=[
            "Some unrelated maintainer comment.",
            "Another contributor said hi.",
            "choir-intake-ack:0000deadbeef0000",  # marker but different hash
        ],
    )
    assert payload["should_post_comment"] is True


def test_error_payload_always_posts() -> None:
    # Even if the same error keeps occurring, the maintainer should keep
    # seeing it. We don't dedup error comments in v0.
    bad = VALID_BODY.replace("type: prove\n", "")
    payload = intake_cli.build_payload(
        bad, repo="org/myproj", existing_comments=["whatever"]
    )
    assert payload["status"] == "error"
    assert payload["should_post_comment"] is True


# ---------------------------------------------------------------------------
# Prover-profile resolution (design note 12 §5) — `--prover` flag and the
# default-branch `.choir/project.toml` fallback.
# ---------------------------------------------------------------------------


def _write_project_toml(workspace, project_body: str) -> None:  # type: ignore[no-untyped-def]
    (workspace / ".choir").mkdir(exist_ok=True)
    (workspace / ".choir" / "project.toml").write_text(
        f"[project]\n{project_body}", encoding="utf-8"
    )


def test_main_prover_flag_rejects_extension_outside_profile(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    body_file = tmp_path / "body.txt"
    body_file.write_text(VALID_BODY, encoding="utf-8")  # target_file: MyProj/Foo.lean

    rc = intake_cli.main(
        ["--body-file", str(body_file), "--repo", "org/myproj", "--prover", "rocq"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert any(e["code"] == "target_file_extension" for e in payload["errors"])


def test_main_prover_flag_accepts_matching_extension(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    body_file = tmp_path / "body.txt"
    body_file.write_text(VALID_BODY.replace("Foo.lean", "Foo.v"), encoding="utf-8")

    rc = intake_cli.main(
        ["--body-file", str(body_file), "--repo", "org/myproj", "--prover", "rocq"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_main_reads_prover_from_cwd_project_toml_rocq_rejects_lean(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    # Simulates the workflow's default-branch checkout: cwd's
    # .choir/project.toml selects "rocq", so a .lean target_file (this
    # project's a Lean holdover, or a copy-paste mistake) is rejected.
    _write_project_toml(tmp_path, 'prover = "rocq"\n')
    monkeypatch.chdir(tmp_path)

    body_file = tmp_path / "body.txt"
    body_file.write_text(VALID_BODY, encoding="utf-8")  # target_file: MyProj/Foo.lean

    rc = intake_cli.main(["--body-file", str(body_file), "--repo", "org/myproj"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert any(e["code"] == "target_file_extension" for e in payload["errors"])


def test_main_accepts_existing_comments_file(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    body_file = tmp_path / "body.txt"
    body_file.write_text(VALID_BODY, encoding="utf-8")

    # First run — generate the comment and capture its hash.
    rc = intake_cli.main(["--body-file", str(body_file), "--repo", "org/myproj"])
    assert rc == 0
    first = json.loads(capsys.readouterr().out)
    h = first["record_hash"]

    # Second run with prior comment present.
    comments_file = tmp_path / "comments.txt"
    # gh --jq '.comments[].body' yields one body per line; preserve that shape.
    comments_file.write_text(
        f"unrelated comment\n<!-- choir-intake-ack:{h} -->\n",
        encoding="utf-8",
    )
    rc = intake_cli.main(
        [
            "--body-file",
            str(body_file),
            "--repo",
            "org/myproj",
            "--existing-comments-file",
            str(comments_file),
        ]
    )
    assert rc == 0
    second = json.loads(capsys.readouterr().out)
    assert second["should_post_comment"] is False
