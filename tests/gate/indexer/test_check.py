"""Tests for `gate.indexer.check`."""

from __future__ import annotations

from gate.indexer.check import (
    find_collisions,
    find_introductions,
    format_findings,
)
from gate.indexer.extract import DeclLocation


def _loc(name: str, file: str, line: int = 1) -> DeclLocation:
    return DeclLocation(name=name, file_path=file, line=line)


# ---------------------------------------------------------------------------
# find_introductions
# ---------------------------------------------------------------------------


def test_introductions_identifies_by_file_and_name() -> None:
    # Same name in different files is a new introduction.
    base = [_loc("foo", "A.lean")]
    head = [_loc("foo", "A.lean"), _loc("foo", "B.lean")]
    intros = find_introductions(base, head)
    assert len(intros) == 1
    assert intros[0].file_path == "B.lean"


def test_introductions_removed_decls_are_not_in_intros() -> None:
    # A decl deleted in head is in base-not-head, which isn't an
    # introduction. We only flag head-not-base.
    base = [_loc("foo", "F.lean"), _loc("bar", "G.lean")]
    head = [_loc("foo", "F.lean")]
    assert find_introductions(base, head) == []


# ---------------------------------------------------------------------------
# find_collisions
# ---------------------------------------------------------------------------


def test_no_collisions_when_intros_have_unique_names() -> None:
    base = [_loc("foo", "F.lean")]
    new = [_loc("bar", "G.lean")]
    assert find_collisions(new, base) == []


def test_collision_when_new_name_matches_existing_base_decl() -> None:
    base = [_loc("Existing.foo", "A.lean", line=10)]
    new = [_loc("Brand_new.foo", "B.lean", line=20)]
    findings = find_collisions(new, base)
    assert len(findings) == 1
    assert findings[0].new_decl.name == "Brand_new.foo"
    assert len(findings[0].existing_locations) == 1
    assert findings[0].existing_locations[0].name == "Existing.foo"


# ---------------------------------------------------------------------------
# format_findings
# ---------------------------------------------------------------------------


def test_format_includes_new_and_existing_locations() -> None:
    base = [_loc("Existing.foo", "A.lean", line=10)]
    new = [_loc("Brand_new.foo", "B.lean", line=20)]
    findings = find_collisions(new, base)
    out = format_findings(findings)
    assert "Brand_new.foo" in out
    assert "B.lean:20" in out
    assert "A.lean:10" in out
    assert "informational" in out.lower() or "not blocking" in out.lower()
