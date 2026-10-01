"""Shapes that broke the statement audits, pinned at the verdict level.

This file is deliberately redundant. Each shape below is also covered by a
focused test added in the round that fixed it — but those live in six files
across `tests/gate/`, and the defects they pin were found in nine rounds of
review, each round finding shapes the previous one's tests did not.

The slice that produced them established, twice, that a shape whose evidence
lives only in a session transcript gets lost: round 1 recorded a
block-commented-declaration sub-shape, round 2's own gate test substituted a
different fixture for it, and the bypass shipped. So the shapes are collected
here too, cross-prover, in one readable list.

Two directions are pinned throughout and the distinction matters:

  UNCHANGED on legitimate work  -- a false block stops a project. Most of
                                   these shapes were false blocks, and three
                                   fired on a file compared against itself.
  CHANGED on a real edit        -- a fail-open lets a rewritten statement
                                   merge. On isabelle and rocq nothing else
                                   binds a non-target declaration.

`gate/checks.py` records the check's class; the module docstring has why it is
advisory.
"""

from __future__ import annotations

import pytest

from gate.provers.base import ProverProfile
from gate.provers.isabelle import ISABELLE
from gate.provers.lean4 import LEAN4
from gate.provers.rocq import ROCQ
from gate.verify.statement_equiv import compare as compare_target
from gate.verify.statement_immutability import compare_declarations


def _verdict(base: str, head: str, profile: ProverProfile = LEAN4) -> str:
    return compare_declarations(base, head, profile=profile)[0].value


# --------------------------------------------------------------------------
# lean4 — a false block on legitimate work.
# --------------------------------------------------------------------------

_STRUCTURE_THEN_ATTRIBUTED = (
    "structure Point where\n"
    "  x : Nat\n"
    "\n"
    "@[simp] theorem px : (1:Nat) = 1 := by\n"
    "  sorry\n"
)


def test_attributed_declaration_is_its_own_span() -> None:
    """`@[simp]` was not a first-token keyword, so the `structure` above it
    swallowed the theorem and filling its `sorry` read as retyping a field."""
    assert _verdict(_STRUCTURE_THEN_ATTRIBUTED,
                    _STRUCTURE_THEN_ATTRIBUTED.replace("sorry", "rfl")) == "unchanged"


# --------------------------------------------------------------------------
# Fail-opens. Each of these let a rewritten statement through.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("label", "base", "head", "profile"),
    [
        ("lean4 modifier-prefixed declaration was invisible",
         "private theorem h : (2:Nat)+2 = 4 := by norm_num\n",
         "private theorem h : (2:Nat)+2 = 5 := by norm_num\n", LEAN4),
        ("lean4 `opaque` was absent from decl_keywords entirely",
         "opaque c : Nat\n", "opaque c : Int\n", LEAN4),
        ("a block-commented copy stood in for a deleted declaration",
         "theorem t : (1:Nat) = 1 := by rfl\n",
         "/-\ntheorem t : (1:Nat) = 1 := by rfl\n-/\nlemma mine : (2:Nat) = 2 := by rfl\n", LEAN4),
        ("a column-zero structure body was outside its own span",
         "structure P where\nx : Nat\n", "structure P where\nx : Int\n", LEAN4),
        ("a definition's body is its meaning, and was uncompared",
         "def foo : Nat := 5\n", "def foo : Nat := 6\n", LEAN4),
        ("rocq control-flag prefixes hid the declaration",
         "Time Definition f : nat := 5.\n", "Time Definition f : bool := true.\n", ROCQ),
        ("rocq `Property` was missing from decl_keywords",
         "Property p : 1 = 1.\nProof. auto. Qed.\n",
         "Property p : 2 = 2.\nProof. auto. Qed.\n", ROCQ),
        ("isabelle modifier-prefixed declaration was invisible",
         'private lemma foo: "P x"\n  by simp\n',
         'private lemma foo: "Q x"\n  by simp\n', ISABELLE),
    ],
)
def test_a_rewritten_statement_is_reported(
    label: str, base: str, head: str, profile: ProverProfile
) -> None:
    assert _verdict(base, head, profile) == "changed", label


# --------------------------------------------------------------------------
# isabelle, via the BLOCKING check. `statement-equiv` is TRUST there and is
# that prover's only statement check, so both directions cost more.
# --------------------------------------------------------------------------

def test_locale_targeted_lemma_is_bound_by_the_blocking_check() -> None:
    """`lemma (in A) foo:` enumerated as `(in`, extraction returned None, and
    the verdict was UNDETERMINED -- which PASSES. The standard way to target a
    locale let any statement rewrite through."""
    base = 'lemma (in A) foo: "P x"\n  by simp\n'
    verdict, _ = compare_target(base, base.replace("P x", "Q x"), "foo", profile=ISABELLE)
    assert verdict.value == "changed"


def test_a_terminal_dot_proof_is_not_a_statement_change() -> None:
    """`.` and `..` are complete Isabelle proofs, but punctuation could not
    join a whole-word stop-token set, so the header scan ran into the proof."""
    verdict, _ = compare_target(
        'lemma foo: "P" .\n', 'lemma foo: "P" by simp\n', "foo", profile=ISABELLE
    )
    assert verdict.value == "equivalent"


def test_an_unrelated_edit_is_not_blamed_on_a_proofless_declaration() -> None:
    """A `definition` has no proof, so with no blank line after it the header
    scan captured the following command -- and editing *that* command reported
    the definition changed, blocking a PR while naming the wrong declaration."""
    base = 'definition f :: "nat" where "f = 1"\nlemma a: "P"\n  sorry\n'
    head = 'definition f :: "nat" where "f = 1"\nlemma a: "Q"\n  by simp\n'
    verdict, _ = compare_target(base, head, "f", profile=ISABELLE)
    assert verdict.value == "equivalent"


def test_a_cartouche_does_not_blank_the_rest_of_the_file() -> None:
    """`\\<open>(*)\\<close>` is HOL's multiplication operator. Read as an
    unterminated comment it blanked everything after it, so one such line near
    the top of a theory made every declaration below it invisible -- and an
    invisible declaration's statement can be rewritten freely. In
    `HOL/Library/Word.thy` the affected span ran from line 54 to line 1348.
    """
    source = 'lift_definition t :: "nat" is \\<open>(*)\\<close>\nlemma m: "P"\n  by simp\n'
    verdict, _ = compare_target(source, source.replace('"P"', '"Q"'), "m", profile=ISABELLE)
    assert verdict.value == "changed"
