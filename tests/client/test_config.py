"""Tests for `client.config`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from client.config import (
    Config,
    ConfigError,
    load_config,
    project_config_path,
)


def _write_config(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def test_load_default_when_no_file(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHOIR_CONFIG", str(tmp_path / "absent.json"))
    assert load_config() == Config.default()


def test_malformed_json_errors(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CHOIR_CONFIG", str(cfg))
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config()


# --- tooling.search ---------------------------------------------------------


def test_tooling_search_not_a_string_errors(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"tooling": {"search": ["a"]}})
    monkeypatch.setenv("CHOIR_CONFIG", str(cfg))
    with pytest.raises(ConfigError, match=r"'tooling\.search' must be a string"):
        load_config()


# --- per-project overlay ----------------------------------------------------


def test_per_project_overrides_global(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHOIR_CONFIG", str(tmp_path / "config.json"))
    _write_config(tmp_path / "config.json", {"tooling": {"search": "none"}})
    _write_config(project_config_path("acme/proofs"), {"tooling": {"search": "loogle"}})
    assert load_config("acme/proofs").tooling.search == "loogle"


def test_per_project_absent_falls_back_to_global(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHOIR_CONFIG", str(tmp_path / "config.json"))
    _write_config(tmp_path / "config.json", {"tooling": {"search": "loogle"}})
    assert load_config("acme/proofs").tooling.search == "loogle"


def test_no_repo_ignores_per_project_override(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CHOIR_CONFIG", str(tmp_path / "config.json"))
    _write_config(tmp_path / "config.json", {"tooling": {"search": "none"}})
    _write_config(project_config_path("acme/proofs"), {"tooling": {"search": "loogle"}})
    assert load_config().tooling.search == "none"
