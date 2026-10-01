"""Tests for the wire-fingerprint guard (design note 13 §2.1).

This is the mechanical enforcement of the `PROTOCOL_VERSION` bump rules:
if any of the surfaces `compute_fingerprint()` hashes drifts from the
committed `protocol_fingerprint.json`, the suite fails with the
actionable instruction block, rather than shipping an unnoticed wire
change. See `gate/protocol_fingerprint.py`'s module docstring for what
counts as a "wire surface."
"""

from __future__ import annotations

import pytest

import gate.protocol_fingerprint as pf
from gate.protocol import PROTOCOL_VERSION

# ---------------------------------------------------------------------------
# Stored snapshot — exists, parses, matches PROTOCOL_VERSION
# ---------------------------------------------------------------------------


def test_stored_protocol_version_matches() -> None:
    stored = pf.load_stored()
    assert stored["protocol_version"] == PROTOCOL_VERSION, pf.format_version_mismatch_message(
        stored["protocol_version"], PROTOCOL_VERSION
    )


# ---------------------------------------------------------------------------
# The guard itself: compute_fingerprint() must match the committed snapshot
# ---------------------------------------------------------------------------


def test_computed_fingerprint_matches_stored_snapshot() -> None:
    stored = pf.load_stored()
    computed = pf.compute_fingerprint()
    added, removed, changed = pf.diff_surfaces(computed, stored["surfaces"])
    assert computed == stored["surfaces"], pf.format_mismatch_message(
        added, removed, changed
    )


# ---------------------------------------------------------------------------
# Version-only mismatch: a stored snapshot whose surfaces still all match
# but whose `protocol_version` is stale must be exactly as actionable as a
# surface mismatch — both trigger conditions emit the full two-option
# instruction block (design note 13 §2, `--update`, and — for the version
# case — both version numbers), never a bare note or a generic assert.
# ---------------------------------------------------------------------------


def test_print_comparison_version_only_mismatch_emits_instruction_block(
    monkeypatch, capsys
) -> None:
    """Reproduces the bug: surfaces untouched, `protocol_version` wrong.

    Before the fix, `_print_comparison` printed only a bare "note:" line
    and fell through to `return 1` with no instruction block at all.
    """
    stored = pf.load_stored()
    tampered_stored = {**stored, "protocol_version": 999}
    monkeypatch.setattr(pf, "load_stored", lambda: tampered_stored)

    exit_code = pf._print_comparison()
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "protocol_version mismatch" in out
    assert "999" in out
    assert str(PROTOCOL_VERSION) in out
    assert "design note 13 §2" in out
    assert "gate.protocol_fingerprint --update" in out


# ---------------------------------------------------------------------------
# required_checks extraction fails loud on ambiguity, instead of silently
# taking the first "contexts" block in the file (which could be an
# unrelated comment).
# ---------------------------------------------------------------------------


def test_parse_required_checks_raises_on_ambiguous_contexts_block() -> None:
    real_text = pf.NEW_PROJECT_SCRIPT.read_text(encoding="utf-8")
    decoy_text = real_text + '\n# example: {"contexts": ["decoy-check"]}\n'

    with pytest.raises(pf.ProtocolFingerprintError, match="ambiguous"):
        pf._parse_required_checks(decoy_text)


# ---------------------------------------------------------------------------
# labels extraction ignores commented-out `gh label create "..."` lines.
# ---------------------------------------------------------------------------


def test_parse_label_vocabulary_ignores_commented_lines() -> None:
    text = (
        '# gh label create "choir/decoy-in-a-comment"\n'
        'gh label create "choir/real-label" --repo "$REPO" --force\n'
    )
    assert pf._parse_label_vocabulary(text) == ["choir/real-label"]
