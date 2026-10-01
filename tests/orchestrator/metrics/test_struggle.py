"""Tests for `orchestrator.metrics.struggle`.

The aggregation is pure (`build_struggle_signals`); the `gh`-calling
collector is covered with a mocked subprocess, mirroring test_collect.py.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from orchestrator.metrics.struggle import (
    IssueRow,
    PRRow,
    build_struggle_signals,
    collect_struggle_signals,
)

NOW = datetime(2026, 6, 18, tzinfo=UTC)


# --- build_struggle_signals ------------------------------------------------


def _issue(n: int, *, created: str = "2026-06-01T00:00:00Z") -> IssueRow:
    return IssueRow(
        number=n,
        title=f"task {n}",
        url=f"https://x/{n}",
        state="open",
        created_at=created,
    )


def _pr(branch: str, state: str, author: str, created: str) -> PRRow:
    return PRRow(head_branch=branch, state=state, author=author, created_at=created)


def test_state_buckets_and_distinct_attempters() -> None:
    prs = [
        _pr("choir/7-a", "CLOSED", "alice", "2026-06-02T00:00:00Z"),
        _pr("choir/7-a", "CLOSED", "bob", "2026-06-05T00:00:00Z"),
        _pr("choir/7-a", "OPEN", "alice", "2026-06-10T00:00:00Z"),
        _pr("choir/7-a", "MERGED", "carol", "2026-06-12T00:00:00Z"),
    ]
    [sig] = build_struggle_signals([_issue(7)], prs, now=NOW)
    assert sig.attempts == 4
    assert sig.failed == 2  # two CLOSED-unmerged
    assert sig.open == 1
    assert sig.merged == 1
    assert sig.distinct_attempters == 3  # alice, bob, carol
    assert sig.last_attempt_age_days == 6  # 2026-06-12 -> 2026-06-18


def test_branch_prefix_does_not_bleed_across_issues() -> None:
    # PRs for #1 must not be counted toward #12 and vice versa.
    prs = [
        _pr("choir/1-x", "CLOSED", "a", "2026-06-02T00:00:00Z"),
        _pr("choir/12-y", "CLOSED", "b", "2026-06-02T00:00:00Z"),
    ]
    sigs = {s.number: s for s in build_struggle_signals(
        [_issue(1), _issue(12)], prs, now=NOW
    )}
    assert sigs[1].failed == 1
    assert sigs[12].failed == 1
    assert sigs[1].attempts == 1
    assert sigs[12].attempts == 1


def test_unlinked_prs_ignored() -> None:
    prs = [_pr("feature/random", "CLOSED", "a", "2026-06-02T00:00:00Z")]
    [sig] = build_struggle_signals([_issue(3)], prs, now=NOW)
    assert sig.attempts == 0


def test_sorted_most_stuck_first() -> None:
    prs = [
        _pr("choir/1-x", "CLOSED", "a", "2026-06-02T00:00:00Z"),
        _pr("choir/2-y", "CLOSED", "a", "2026-06-02T00:00:00Z"),
        _pr("choir/2-y", "CLOSED", "b", "2026-06-03T00:00:00Z"),
    ]
    sigs = build_struggle_signals([_issue(1), _issue(2)], prs, now=NOW)
    # #2 has 2 failures, #1 has 1 — #2 sorts first.
    assert [s.number for s in sigs] == [2, 1]


# --- collect_struggle_signals (mocked gh) ----------------------------------


@dataclass
class _FakeProc:
    stdout: str
    stderr: str = ""
    returncode: int = 0


def test_collect_struggle_signals_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    issue_payload = json.dumps([
        {
            "number": 7,
            "title": "prove foo",
            "url": "https://x/7",
            "state": "OPEN",
            "createdAt": "2026-06-01T00:00:00Z",
        }
    ])
    pr_payload = json.dumps([
        {
            "headRefName": "choir/7-foo",
            "state": "CLOSED",
            "author": {"login": "alice"},
            "createdAt": "2026-06-05T00:00:00Z",
        },
        {
            "headRefName": "choir/7-foo",
            "state": "OPEN",
            "author": {"login": "bob"},
            "createdAt": "2026-06-10T00:00:00Z",
        },
    ])

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        # args == ["gh", <subcommand>, ...]
        return _FakeProc(stdout=issue_payload if args[1] == "issue" else pr_payload)

    monkeypatch.setattr(subprocess, "run", fake_run)
    signals = collect_struggle_signals("alice/proj", now=NOW)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.number == 7
    assert sig.failed == 1
    assert sig.open == 1
    assert sig.distinct_attempters == 2
