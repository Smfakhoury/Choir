"""Tests for `client.pins`."""

from __future__ import annotations

from pathlib import Path

from client.pins import (
    DetectionStatus,
    Pins,
    check_pins,
    format_pin_report,
    read_pins,
)

# ---------------------------------------------------------------------------
# read_pins
# ---------------------------------------------------------------------------


def _write_pins(workspace: Path, content: str) -> None:
    pins_dir = workspace / ".choir"
    pins_dir.mkdir(parents=True, exist_ok=True)
    (pins_dir / "pins.toml").write_text(content, encoding="utf-8")


def test_read_pins_malformed_toml_returns_empty(tmp_path: Path) -> None:
    _write_pins(tmp_path, "this is not valid toml [[[")
    pins = read_pins(tmp_path)
    # Malformed → empty pins (don't crash the workspace setup).
    assert pins == Pins()


# ---------------------------------------------------------------------------
# check_pins (with detection mocked)
# ---------------------------------------------------------------------------


def test_check_pins_no_file_returns_empty(tmp_path: Path) -> None:
    assert check_pins(tmp_path) == []


def test_check_pins_with_lean4_skills_pin_not_installed(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "client.pins.detect_lean4_skills_version",
        lambda: (None, DetectionStatus.NOT_INSTALLED),
    )
    _write_pins(tmp_path, '[pins]\nlean4_skills = "v0.2.3"\n')
    checks = check_pins(tmp_path)
    assert len(checks) == 1
    assert checks[0].name == "lean4-skills"
    assert checks[0].pinned == "v0.2.3"
    assert checks[0].observed is None
    assert checks[0].status == DetectionStatus.NOT_INSTALLED
    # Undetectable is treated as match (advisory, not blocking).
    assert checks[0].matches is True


def test_check_pins_matching_version(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "client.pins.detect_lean4_skills_version",
        lambda: ("v0.2.3", DetectionStatus.OBSERVED),
    )
    _write_pins(tmp_path, '[pins]\nlean4_skills = "v0.2.3"\n')
    checks = check_pins(tmp_path)
    assert len(checks) == 1
    assert checks[0].matches is True
    assert checks[0].observed == "v0.2.3"
    assert checks[0].status == DetectionStatus.OBSERVED


def test_check_pins_version_mismatch(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "client.pins.detect_lean4_skills_version",
        lambda: ("v0.1.0", DetectionStatus.OBSERVED),
    )
    _write_pins(tmp_path, '[pins]\nlean4_skills = "v0.2.3"\n')
    checks = check_pins(tmp_path)
    assert len(checks) == 1
    assert checks[0].matches is False
    assert checks[0].observed == "v0.1.0"
    assert checks[0].pinned == "v0.2.3"
    assert checks[0].status == DetectionStatus.OBSERVED


# ---------------------------------------------------------------------------
# format_pin_report
# ---------------------------------------------------------------------------


def test_format_pin_report_empty() -> None:
    assert format_pin_report([]) == ""
