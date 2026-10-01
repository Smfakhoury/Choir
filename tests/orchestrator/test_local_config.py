"""Tests for `orchestrator.local_config`."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import local_config
from orchestrator.local_config import (
    LocalConfig,
    LocalConfigError,
    parse_local_config,
    read_local_config,
)


def test_full_config_parses() -> None:
    cfg = parse_local_config(
        '[project]\nrepo = "a/b"\ncheckout = "~/work/b"\n'
        "[loop]\npoll_interval_seconds = 120\nmax_wait_seconds = 900\n"
    )
    assert cfg.repo == "a/b"
    assert cfg.checkout == Path("~/work/b").expanduser()
    assert cfg.poll_interval_seconds == 120
    assert cfg.max_wait_seconds == 900


def test_zero_interval_rejected() -> None:
    with pytest.raises(LocalConfigError, match="positive integer"):
        parse_local_config("[loop]\npoll_interval_seconds = 0\n")


# --- per-project resolution (multi-project on one machine) -----------------


def _redirect_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(local_config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(
        local_config, "ORCHESTRATOR_CONFIG_PATH", tmp_path / "orchestrator.toml"
    )


def test_per_project_preferred_over_legacy(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _redirect_paths(monkeypatch, tmp_path)
    (tmp_path / "orchestrator.toml").write_text(
        '[project]\nrepo = "legacy/repo"\n', encoding="utf-8"
    )
    pp = tmp_path / "projects" / "alice" / "proj" / "orchestrator.toml"
    pp.parent.mkdir(parents=True)
    pp.write_text('[project]\ncheckout = "/work/proj"\n', encoding="utf-8")
    cfg = read_local_config(repo="alice/proj")
    assert cfg.checkout == Path("/work/proj")  # per-project file used


def test_falls_back_to_legacy_when_no_per_project(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _redirect_paths(monkeypatch, tmp_path)
    (tmp_path / "orchestrator.toml").write_text(
        '[project]\nrepo = "legacy/repo"\n', encoding="utf-8"
    )
    assert read_local_config(repo="alice/proj").repo == "legacy/repo"


def test_repo_with_nothing_present_defaults(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _redirect_paths(monkeypatch, tmp_path)
    assert read_local_config(repo="alice/proj") == LocalConfig()
