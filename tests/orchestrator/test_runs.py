"""Tests for `orchestrator.runs` — workflow runs held awaiting approval.

The situation this exists for: under spec D4 every contribution is a fork PR,
and a held run makes that PR show *no checks at all*. `merge_pr` refuses it —
correctly, since that is also what a PR which deleted its workflows looks
like. These two need opposite responses, so the orchestrator has to be able
to tell them apart.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from orchestrator.runs import (
    RunError,
    approve_runs_for_sha,
    pending_approvals,
)


class _FakeProc:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _run_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 4242,
        "name": "verify-axiom-honesty",
        "head_sha": "b" * 40,
        "head_branch": "choir/12-foo",
        "event": "pull_request",
        "actor": {"login": "contributor"},
        "html_url": "https://github.com/alice/proj/actions/runs/4242",
    }
    base.update(overrides)
    return base


def test_unreadable_output_raises_rather_than_reporting_nothing_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently returning `[]` would read as "nothing is waiting", which is
    the answer that makes a stalled queue look like an idle one."""
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: _FakeProc(stdout="not json")
    )
    with pytest.raises(RunError, match="unreadable"):
        pending_approvals("alice/proj")


def test_approving_by_sha_leaves_other_prs_runs_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval runs a stranger's code on your runners, so it is scoped to
    the exact tree the orchestrator just reviewed — never "approve
    everything held"."""
    reviewed = "b" * 40
    other = "c" * 40
    payload = {
        "workflow_runs": [
            _run_payload(id=1, head_sha=reviewed),
            _run_payload(id=2, head_sha=other),
            _run_payload(id=3, head_sha=reviewed, name="verify-sorry"),
        ]
    }
    approved: list[list[str]] = []

    def fake_run(cmd, **k):  # type: ignore[no-untyped-def]
        if "POST" in cmd:
            approved.append(cmd)
            return _FakeProc(stdout="")
        return _FakeProc(stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = approve_runs_for_sha("alice/proj", reviewed)
    assert [r.run_id for r in result] == [1, 3]
    assert len(approved) == 2
    assert not any("/runs/2/approve" in " ".join(c) for c in approved)
