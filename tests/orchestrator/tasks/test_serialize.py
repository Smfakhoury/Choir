"""Tests for `orchestrator.tasks.serialize`.

The load-bearing property: every body produced by `task_to_body` must
round-trip through the intake parser. If this ever fails the intake
workflow would reject issues that the maintainer library created.
"""

from __future__ import annotations

from gate.state.intake import ParseSuccess, parse_issue_body
from gate.state.task_record import ProjectRef, TaskRecord, TaskType
from orchestrator.tasks.serialize import task_to_body


def _record(**overrides) -> TaskRecord:  # type: ignore[no-untyped-def]
    defaults = dict(
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
    defaults.update(overrides)
    return TaskRecord(**defaults)


def test_task_to_body_roundtrips_through_intake() -> None:
    task = _record()
    body = task_to_body(task, "Prove that 1+1=2.")
    result = parse_issue_body(body)
    assert isinstance(result, ParseSuccess)
    assert result.record == task
    assert "Prove that 1+1=2." in result.body_prose
