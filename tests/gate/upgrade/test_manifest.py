"""Tests for `gate.upgrade.manifest` — the overlay install manifest.

Covers the data model (parse/serialize round-trip, stable output), the
absent-vs-corrupt distinction that keeps a corrupt manifest from silently
restarting retirement tracking, the path safety rails that stop a
hand-edited manifest from deleting files outside the project, and the
retirement decision table.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from gate.upgrade.manifest import (
    CLASS_MANAGED,
    MANIFEST_VERSION,
    Entry,
    ManifestError,
    Retirement,
    build_manifest,
    load_manifest,
    plan_retirements,
    unmanaged_notices,
    validate_relpath,
)

WF = ".github/workflows/"


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "../../outside.yml",
        ".github/../../outside.yml",
        "",
        ".",
        "./",
    ],
)
def test_validate_relpath_refuses_unsafe_paths(bad: str) -> None:
    with pytest.raises(ManifestError):
        validate_relpath(bad)


def test_load_manifest_rejects_unknown_manifest_version() -> None:
    with pytest.raises(ManifestError):
        load_manifest(json.dumps({"manifest_version": 99, "files": {}}))


def test_load_manifest_rejects_unsafe_path_in_files() -> None:
    text = json.dumps(
        {
            "manifest_version": MANIFEST_VERSION,
            "files": {"../../etc/cron.d/x": {"class": "managed", "sha256": "0" * 64}},
        }
    )
    with pytest.raises(ManifestError):
        load_manifest(text)


# ---------------------------------------------------------------------------
# retirement decision table
# ---------------------------------------------------------------------------


def _plan(
    previous_entries: list[Entry],
    overlay: set[str],
    on_disk: Mapping[str, str | None],
) -> list[Retirement]:
    return plan_retirements(build_manifest(previous_entries), overlay, on_disk)


def test_unchanged_overlay_set_retires_nothing() -> None:
    entry = Entry(f"{WF}verify-style.yml", CLASS_MANAGED, "a" * 64)
    assert _plan([entry], {entry.path}, {entry.path: "a" * 64}) == []


# ---------------------------------------------------------------------------
# seed-mode notice
# ---------------------------------------------------------------------------


def test_unmanaged_notices_ignores_paths_outside_the_two_directories() -> None:
    assert unmanaged_notices(["README.md", "gate/checks.py"], set()) == []
