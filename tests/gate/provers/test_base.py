"""Tests for `gate.provers` — the profile dataclasses and registry."""

from __future__ import annotations

import pytest

from gate.provers import PROFILES, ProverError, get_profile

# ---------------------------------------------------------------------------
# Registry invariants (design note 12 §10)
# ---------------------------------------------------------------------------


def test_every_profile_supplies_a_declaration_qualifier() -> None:
    # The field is typed optional for consumers that can fall back to a
    # surface name, but `gate.verify.sorry_delta.compare_reduction`
    # cannot: its per-declaration count key and its refusal of a key
    # two declarations share are both computed from this hook. A profile
    # without one counts placeholders per surface name, pooling two
    # same-named declarations in sibling scopes into one count, and both
    # of those rules go inert.
    for profile in PROFILES.values():
        assert profile.qualify_decl_names is not None, profile.name


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


def test_get_profile_unknown_raises_prover_error_listing_valid_names() -> None:
    with pytest.raises(ProverError, match="lean4"):
        get_profile("nope")
