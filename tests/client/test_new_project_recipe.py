"""Guard: `new-project.sh --prover` wiring (design note 12 §7).

Mirrors `tests/client/test_join_recipe.py`'s precedent for smoke-checking
shell scripts that have no bash test harness: grep the script for the
load-bearing substrings rather than executing the whole bootstrap flow
(which needs a live `gh` session). A `bash -n` syntax check backs the
grep checks with an actual parse.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "new-project.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_new_project_sh_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_project_toml_writes_protocol_pin() -> None:
    # design note 13 §3 — bootstrap writes the pin alongside prover, in
    # the same [project] heredoc, computed from the running Choir
    # checkout at bootstrap time.
    text = _text()
    assert "CHOIR_PROTOCOL_VERSION" in text
    assert "CHOIR_BOOTSTRAP_COMMIT" in text
    assert "choir_protocol = $CHOIR_PROTOCOL_VERSION" in text
    assert 'choir_commit = "$CHOIR_BOOTSTRAP_COMMIT"' in text
    assert "from gate.protocol import PROTOCOL_VERSION" in text


def test_rocq_skeleton_has_dune_coq_theory_stanza() -> None:
    # Without a `dune` file declaring the coq theory, `dune build` compiles
    # no .v files — so the generated rocq skeleton must ship one.
    text = _text()
    assert 'cat > "$PROJECT/$LIB/dune"' in text
    assert "(coq.theory" in text


def test_fstar_skeleton_ships_the_verify_target_the_gate_invokes() -> None:
    # gate/provers/fstar.py sets build_command=("make", "verify"), so a
    # generated F* project without a Makefile `verify` target would fail
    # the rebuild on every PR rather than at bootstrap, where it is cheap
    # to notice.
    text = _text()
    assert 'cat > "$PROJECT/Makefile"' in text
    assert "verify:" in text


def test_fstar_verify_loop_fails_the_build_on_a_failed_module() -> None:
    # The F* recipe verifies one file per invocation (current F* resolves
    # dependencies on the fly and rejects multiple files on the command
    # line). Without `set -e` the shell loop would swallow a failed module
    # and the rebuild gate would pass vacuously — the one failure mode
    # that makes a green PR meaningless.
    assert "@set -e; for f in" in _text()


def test_all_provers_ship_verify_trust_report() -> None:
    # Each of the four prover branches (lean4, isabelle, rocq, fstar)
    # generates a verify-trust-report workflow — one
    # `name: verify-trust-report` apiece.
    assert _text().count("name: verify-trust-report") == 4
