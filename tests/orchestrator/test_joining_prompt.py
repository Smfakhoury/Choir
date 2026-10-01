"""Tests for `orchestrator.joining_prompt` — the hardcoded contributor prompt."""

from __future__ import annotations

from orchestrator.joining_prompt import joining_prompt


def test_contains_repo_everywhere_needed() -> None:
    text = joining_prompt("alice/proj")
    assert "**`alice/proj`**" in text
    assert "join.sh alice/proj" in text
