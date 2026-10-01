"""Tests for `client.status`."""

from __future__ import annotations

from pathlib import Path

from client.status import list_workspaces
from client.workspace import LeaseMetadata


def _write_lease(path: Path, **overrides: object) -> None:
    base = {
        "repo": "alice/proj",
        "issue": 42,
        "branch": "choir/42-add-comm",
        "pinned_commit": "1a2b3c4d",
        "claimed_at": "2026-05-10T15:32:00+00:00",
        "claimed_by": "alice",
        "target_file": "MyProj/Foo.lean",
        "target_decl": "MyProj.Foo.add_comm",
        "task_type": "prove",
    }
    base.update(overrides)
    path.mkdir(parents=True, exist_ok=True)
    LeaseMetadata(**base).write(path / ".choir-lease.json")  # type: ignore[arg-type]


def test_single_workspace(tmp_path: Path) -> None:
    _write_lease(tmp_path / "alice" / "proj" / "42")
    entries = list_workspaces(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    assert e.repo == "alice/proj"
    assert e.issue == 42
    assert e.target_decl == "MyProj.Foo.add_comm"
    assert e.workspace_path == tmp_path / "alice" / "proj" / "42"


def test_sorted_by_claimed_at_descending(tmp_path: Path) -> None:
    _write_lease(
        tmp_path / "alice" / "proj" / "1",
        issue=1,
        claimed_at="2026-05-10T09:00:00+00:00",
    )
    _write_lease(
        tmp_path / "alice" / "proj" / "2",
        issue=2,
        claimed_at="2026-05-10T15:00:00+00:00",
    )
    _write_lease(
        tmp_path / "alice" / "proj" / "3",
        issue=3,
        claimed_at="2026-05-10T12:00:00+00:00",
    )
    entries = list_workspaces(tmp_path)
    assert [e.issue for e in entries] == [2, 3, 1]


def test_skips_malformed_metadata(tmp_path: Path) -> None:
    _write_lease(tmp_path / "alice" / "proj" / "1", issue=1)
    bad = tmp_path / "alice" / "proj" / "2"
    bad.mkdir(parents=True)
    (bad / ".choir-lease.json").write_text("{not valid json", encoding="utf-8")
    entries = list_workspaces(tmp_path)
    assert len(entries) == 1
    assert entries[0].issue == 1
