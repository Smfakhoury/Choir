"""Tests for `orchestrator.metrics.collect`.

Mocks the `gh` subprocess; integration against a real repo is left to
the demo runbook.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from gate.state.task_record import ProjectRef, TaskRecord, TaskType
from orchestrator.metrics.collect import collect_task_metrics
from orchestrator.tasks.serialize import task_to_body


@dataclass
class _FakeProc:
    stdout: str
    stderr: str = ""
    returncode: int = 0


def _task() -> TaskRecord:
    return TaskRecord(
        choir_task_version=1,
        type=TaskType.PROVE,
        target_file="Sample/Foo.lean",
        target_decl="Sample.foo",
        project_ref=ProjectRef(
            repo="alice/proj",
            commit="abcdef1234567",
            toolchain="leanprover/lean4:v4.5.0",
        ),
        deps=[],
        blueprint_ref=None,
    )


# ---------------------------------------------------------------------------
# collect_task_metrics
# ---------------------------------------------------------------------------


def test_collect_basic(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    body = task_to_body(_task())
    payload = json.dumps([
        {
            "number": 1,
            "title": "prove foo",
            "url": "https://x/1",
            "state": "OPEN",
            "labels": [
                {"name": "choir/task"},
                {"name": "choir/type:prove"},
                {"name": "choir/available"},
            ],
            "body": body,
            "createdAt": "2026-05-01T12:00:00Z",
            "closedAt": None,
            "assignees": [],
        }
    ])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(stdout=payload))
    out = collect_task_metrics("alice/proj")
    assert len(out) == 1
    m = out[0]
    assert m.number == 1
    assert m.state == "open"
    assert m.task_type == "prove"
    assert m.closed_at is None
    assert m.duration_seconds is None
    assert m.contributor is None
    assert "choir/task" in m.labels


def test_collect_falls_back_to_type_label_when_body_invalid(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Issue body doesn't parse, but the type-label is still there.
    # The metric should pick up `task_type` from the label.
    payload = json.dumps([
        {
            "number": 3,
            "title": "broken",
            "url": "https://x/3",
            "state": "open",
            "labels": [{"name": "choir/task"}, {"name": "choir/type:golf"}],
            "body": "totally garbage no frontmatter",
            "createdAt": "2026-05-01T12:00:00Z",
            "closedAt": None,
            "assignees": [],
        }
    ])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(stdout=payload))
    out = collect_task_metrics("alice/proj")
    assert out[0].task_type == "golf"
