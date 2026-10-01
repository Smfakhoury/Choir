"""Tests for `client._subprocess`."""

from __future__ import annotations

import pytest

from client._subprocess import ToolNotFound, run


def test_run_reports_failure_without_raising() -> None:
    result = run(["false"])
    assert result.returncode != 0
    assert result.ok is False


def test_run_raises_tool_not_found_for_missing_binary() -> None:
    with pytest.raises(ToolNotFound, match="this-command-does-not-exist-xyzzy"):
        run(["this-command-does-not-exist-xyzzy"])
