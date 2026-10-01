"""Tests for `gate.verify.comparator` — pure logic (design note 14 §4–6)."""

from __future__ import annotations

import pytest

from gate.verify.comparator import (
    CHALLENGE_PREFIX,
    CORE_PERMITTED_AXIOMS,
    ComparatorConfigError,
    Outcome,
    challenge_root,
    classify_output,
    declared_names,
    imported_modules,
    lean_lib_names,
    parse_toolchain_version,
    permitted_axioms,
    private_decl_names,
    private_names_in_statement,
    rewrite_imports,
    suffix_divergent_instances,
    toolchain_supported,
    workspace_lakefile,
)
from gate.verify.config import (
    AxiomHonestyConfig,
    AxiomPolicy,
    VerifyConfig,
)

# ---------------------------------------------------------------------------
# toolchain floor
# ---------------------------------------------------------------------------


def test_parse_toolchain_version_reads_every_pin_spelling() -> None:
    assert parse_toolchain_version("leanprover/lean4:v4.31.0") == (4, 31)
    assert parse_toolchain_version("leanprover/lean4:v4.33.0-rc1") == (4, 33)
    assert parse_toolchain_version("leanprover/lean4:v4.14.0\n") == (4, 14)
    assert parse_toolchain_version("4.31.0") == (4, 31)
    assert parse_toolchain_version("nightly-2026-01-01") is None
    assert parse_toolchain_version("") is None


def test_toolchain_supported_reads_the_floor() -> None:
    assert toolchain_supported("leanprover/lean4:v4.27.0") is True
    assert toolchain_supported("leanprover/lean4:v4.31.0") is True
    assert toolchain_supported("leanprover/lean4:v5.0.0") is True
    assert toolchain_supported("leanprover/lean4:v4.14.0") is False
    # Unparseable is neither supported nor refused — the caller decides.
    assert toolchain_supported("nightly-2026-01-01") is None


# ---------------------------------------------------------------------------
# import rewriting
# ---------------------------------------------------------------------------

MODS = frozenset({"Proj", "Proj.Basic"})


def test_rewrite_only_whole_module_match() -> None:
    # `Projection` shares a prefix with `Proj` but is not an internal module.
    src = "import Projection\n"
    assert rewrite_imports(src, MODS) == src


# ---------------------------------------------------------------------------
# lakefile handling
# ---------------------------------------------------------------------------

SAMPLE_LAKEFILE = 'name = "proj"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "Proj"\n'


def test_lean_lib_names_bad_toml() -> None:
    with pytest.raises(ComparatorConfigError):
        lean_lib_names("name = [unclosed")


def test_workspace_lakefile_appends_three_libs() -> None:
    out = workspace_lakefile(SAMPLE_LAKEFILE)
    assert out.startswith(SAMPLE_LAKEFILE)
    for lib in ("Challenge", "Solution", "ChoirBase"):
        assert f'name = "{lib}"' in out
    assert lean_lib_names(out) == ["Proj", "Challenge", "Solution", "ChoirBase"]


# ---------------------------------------------------------------------------
# generated roots
# ---------------------------------------------------------------------------


def test_challenge_root_imports_prefixed() -> None:
    out = challenge_root(["Proj"], "Proj.Basic")
    assert f"import {CHALLENGE_PREFIX}.Proj\n" in out
    assert f"import {CHALLENGE_PREFIX}.Proj.Basic\n" in out


# ---------------------------------------------------------------------------
# permitted axioms
# ---------------------------------------------------------------------------


def test_permitted_axioms_whitelist_union() -> None:
    cfg = VerifyConfig(
        axiom_honesty=AxiomHonestyConfig(
            policy=AxiomPolicy.WHITELIST,
            allowed_axioms=("propext", "MyProject.bigConjecture"),
        )
    )
    assert permitted_axioms(cfg) == (*CORE_PERMITTED_AXIOMS, "MyProject.bigConjecture")


def test_permitted_axioms_net_zero_ignores_allowed_list() -> None:
    cfg = VerifyConfig(
        axiom_honesty=AxiomHonestyConfig(
            policy=AxiomPolicy.NET_ZERO,
            allowed_axioms=("MyProject.bigConjecture",),
        )
    )
    assert permitted_axioms(cfg) == CORE_PERMITTED_AXIOMS


# ---------------------------------------------------------------------------
# verdict classification
# ---------------------------------------------------------------------------


def test_classify_statement_mismatch() -> None:
    outcome, msg, _ = classify_output(
        1, "uncaught exception: Challenge and solution theorem statement do not match: 'Proj.tgt'"
    )
    assert outcome is Outcome.STATEMENT_MISMATCH
    assert "Proj.tgt" in msg


def test_classify_missing_constant_variants() -> None:
    for text in (
        "Const not found in challenge 'Proj.helper'",
        "Const not found in solution: 'Proj.tgt'",
        "Const does not match between challenge and target 'Proj.dep'",
    ):
        outcome, _, _ = classify_output(1, text)
        assert outcome is Outcome.MISSING_CONSTANT, text


def test_tool_error_carries_full_output():
    output = (
        "info: building solution\n"
        "error: ./Foo.lean:3:0: unknown identifier 'bar'\n"
        "uncaught exception: Child exited with 1\n"
    )
    outcome, message, full = classify_output(1, output)
    assert outcome is Outcome.TOOL_ERROR
    # summary stays the last line, for the one-line report
    assert message == "uncaught exception: Child exited with 1"
    # but the diagnosable part must survive
    assert "unknown identifier 'bar'" in full


def test_missing_landrun_classifies_as_sandbox_unavailable() -> None:
    output = (
        "info: building Challenge\n"
        "could not execute external process 'landrun'\n"
        "uncaught exception: Child exited with 255\n"
    )
    outcome, message, full = classify_output(255, output)
    assert outcome is Outcome.SANDBOX_UNAVAILABLE
    assert "landrun" in message
    assert "could not execute external process" in full


def test_solution_build_failure_classifies_distinctly() -> None:
    output = (
        "info: building Challenge\n"
        "info: building Solution\n"
        "./Foo.lean:12:4: error: ring_nf made no progress on the goal\n"
        "error: build failed\n"
        "uncaught exception: Child exited with 1\n"
    )
    outcome, _message, full = classify_output(1, output)
    assert outcome is Outcome.SOLUTION_BUILD_FAILED
    assert "error: build failed" in full
    # the prover diagnostic must survive — it is the actionable part
    assert "ring_nf made no progress" in full


def test_statement_mismatch_still_wins_over_build_noise() -> None:
    """A real verdict outranks incidental build chatter."""
    output = (
        "error: build failed\n"
        "The theorem statement do not match\n"
    )
    outcome, _message, _full = classify_output(1, output)
    assert outcome is Outcome.STATEMENT_MISMATCH


def test_statement_mismatch_still_wins_over_sandbox_noise() -> None:
    """A real verdict outranks sandbox noise, not just build noise.

    Pins the landrun pattern's position *behind* the verdict patterns — the
    build-noise test only pins `error: build failed`'s position, so without
    this a refactor hoisting the infra pattern would mask a real verdict.
    """
    output = (
        "could not execute external process 'landrun'\n"
        "The theorem statement do not match\n"
    )
    outcome, _message, _full = classify_output(1, output)
    assert outcome is Outcome.STATEMENT_MISMATCH


# ---------------------------------------------------------------------------
# private declarations in a target's statement
# ---------------------------------------------------------------------------

_SOURCE = """\
import Mathlib

namespace Proj

private def IsGreedyRule (d : ℝ) (pick : Nat → Nat) : Prop :=
  ∀ n, pick n = n

def PublicPred (d : ℝ) : Prop := d > 0

private theorem helper_bound (d : ℝ) : d ≤ d := le_refl d

theorem exists_greedy_rule (d : ℝ) (hd : 0 < d) :
    ∃ pick : Nat → Nat, IsGreedyRule d pick := by
  sorry

theorem uses_only_public (d : ℝ) : PublicPred d ∨ d ≤ 0 := by
  sorry

theorem mentions_private_in_body_only (d : ℝ) : d ≤ d := by
  exact helper_bound d

end Proj
"""


def test_a_private_declaration_in_the_statement_is_reported() -> None:
    assert private_names_in_statement(_SOURCE, "Proj.exists_greedy_rule") == [
        "IsGreedyRule"
    ]


def test_a_public_only_statement_reports_nothing() -> None:
    assert private_names_in_statement(_SOURCE, "Proj.uses_only_public") == []


def test_a_private_name_used_only_in_the_body_is_not_reported() -> None:
    """The body is a kernel-checked proof; only the statement has to match."""
    assert (
        private_names_in_statement(_SOURCE, "Proj.mentions_private_in_body_only") == []
    )


def test_a_private_target_does_not_report_itself() -> None:
    assert private_names_in_statement(_SOURCE, "Proj.helper_bound") == []


def test_a_substring_of_a_longer_name_is_not_a_match() -> None:
    source = """\
private def Rule : Prop := True

theorem t : IsRuleLike → True := by sorry
"""
    assert private_names_in_statement(source, "t") == []


def test_modifiers_between_private_and_the_keyword_are_tolerated() -> None:
    source = "private noncomputable def Weird : Nat := 0\n"
    assert private_decl_names(source) == {"Weird"}


# ---------------------------------------------------------------------------
# anonymous instances whose generated name reads the module root
# ---------------------------------------------------------------------------

_INSTANCES = """\
import Mathlib

namespace Proj

def uniformPerm (n : ℕ) : Measure (Equiv.Perm (Fin n)) := 0

instance : MeasurableSpace (Equiv.Perm (Fin n)) := ⊤

instance instPermMeasurable : MeasurableSpace (Equiv.Perm (Fin n)) := ⊤

instance : IsProbabilityMeasure (uniformPerm n) := by sorry

end Proj
"""


def test_an_anonymous_instance_over_foreign_types_is_reported() -> None:
    headers = suffix_divergent_instances(_INSTANCES, declared_names(_INSTANCES))
    assert headers == ["instance : MeasurableSpace (Equiv.Perm (Fin n))"]


def test_a_project_name_in_the_body_does_not_rescue_the_header() -> None:
    source = "def helper : Nat := 0\ninstance : Inhabited Nat := ⟨helper⟩\n"
    assert suffix_divergent_instances(source, {"helper"}) == [
        "instance : Inhabited Nat"
    ]


def test_a_where_body_ends_the_header() -> None:
    source = "instance : Inhabited Nat where\n  default := 0\n"
    assert suffix_divergent_instances(source, set()) == ["instance : Inhabited Nat"]


def test_a_substring_of_a_project_name_does_not_rescue_the_header() -> None:
    source = "instance : Inhabited Nat := ⟨0⟩\n"
    assert suffix_divergent_instances(source, {"Na"}) == ["instance : Inhabited Nat"]


def test_imported_modules_reads_the_import_header() -> None:
    assert imported_modules("import Mathlib\nimport Proj.Basic\n\ndef x := 0\n") == [
        "Mathlib",
        "Proj.Basic",
    ]
