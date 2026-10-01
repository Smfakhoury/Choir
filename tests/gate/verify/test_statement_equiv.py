"""Tests for `gate.verify.statement_equiv`."""

from __future__ import annotations

import textwrap

from gate.provers.isabelle import ISABELLE
from gate.provers.rocq import ROCQ
from gate.verify.statement_equiv import (
    Verdict,
    compare,
    extract_statement,
)

# ---------------------------------------------------------------------------
# extract_statement
# ---------------------------------------------------------------------------


def test_extract_simple_theorem() -> None:
    src = "theorem foo : 1 = 1 := rfl\n"
    assert extract_statement(src, "foo") == "theorem foo : 1 = 1 :="


def test_extract_multiline_statement() -> None:
    src = textwrap.dedent(
        """\
        theorem big
            (h : P)
            (k : Q)
            : R := by
          sorry
        """
    )
    out = extract_statement(src, "big")
    assert out is not None
    assert out.startswith("theorem big")
    assert out.endswith(":=")
    assert "(h : P)" in out
    assert "(k : Q)" in out


def test_extract_finds_named_among_multiple() -> None:
    src = textwrap.dedent(
        """\
        theorem foo : 1 = 1 := rfl
        theorem bar : 2 = 2 := rfl
        theorem baz : 3 = 3 := rfl
        """
    )
    assert extract_statement(src, "bar") == "theorem bar : 2 = 2 :="


def test_extract_indented_decl_inside_namespace() -> None:
    src = textwrap.dedent(
        """\
        namespace Foo
          theorem bar : 1 = 1 := rfl
        end Foo
        """
    )
    out = extract_statement(src, "Foo.bar")
    assert out == "theorem bar : 1 = 1 :="


def test_extract_fully_qualified_in_file() -> None:
    src = "theorem Foo.bar : 1 = 1 := rfl\n"
    assert extract_statement(src, "Foo.bar") == "theorem Foo.bar : 1 = 1 :="


def test_extract_returns_none_when_decl_missing() -> None:
    src = "theorem foo : 1 = 1 := rfl\n"
    assert extract_statement(src, "bar") is None


def test_extract_handles_apostrophe_in_name() -> None:
    src = "theorem foo' : 1 = 1 := rfl\n"
    assert extract_statement(src, "foo'") == "theorem foo' : 1 = 1 :="


def test_extract_doesnt_match_substring_in_name() -> None:
    # Searching for "foo" shouldn't match "football".
    src = "theorem football : 1 = 1 := rfl\n"
    assert extract_statement(src, "foo") is None


# ---------------------------------------------------------------------------
# Bug #1 regression: `:=` inside parens (default-valued params, etc.)
# ---------------------------------------------------------------------------


def test_extract_handles_default_valued_parameter() -> None:
    # `theorem foo (n : Nat := 0) : True := trivial` was previously
    # extracted as `theorem foo (n : Nat :=` (stopped at first `:=`).
    # With balanced-paren scanning, the inside-paren `:=` is skipped.
    src = "theorem foo (n : Nat := 0) : True := trivial\n"
    out = extract_statement(src, "foo")
    assert out is not None
    assert out.endswith(":=")
    assert "(n : Nat := 0)" in out
    assert "True" in out


def test_extract_handles_implicit_binders_with_assignments() -> None:
    src = "theorem foo {α : Type := Nat} (x : α) : x = x := rfl\n"
    out = extract_statement(src, "foo")
    assert out is not None
    assert "{α : Type := Nat}" in out
    assert "x = x" in out


def test_attack_weaken_statement_with_default_param_is_caught() -> None:
    # The smoking-gun from the code review: prior to the fix this
    # passed silently because extracts compared only the prefix.
    base = "theorem one_add_one (n : Nat := 0) : (1 : Nat) + 1 = 2 := by sorry\n"
    head = "theorem one_add_one (n : Nat := 0) : True := trivial\n"
    verdict, msg = compare(base, head, "one_add_one")
    assert verdict == Verdict.CHANGED
    assert "differs" in msg


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


_BASE = textwrap.dedent(
    """\
    theorem one_add_one : (1 : Nat) + 1 = 2 := by sorry
    """
)


def test_compare_equivalent_after_closing_sorry() -> None:
    head = "theorem one_add_one : (1 : Nat) + 1 = 2 := rfl\n"
    verdict, msg = compare(_BASE, head, "one_add_one")
    assert verdict == Verdict.EQUIVALENT
    assert "unchanged" in msg


def test_compare_changed_when_statement_weakened() -> None:
    head = "theorem one_add_one : True := trivial\n"
    verdict, msg = compare(_BASE, head, "one_add_one")
    assert verdict == Verdict.CHANGED
    assert "differs" in msg
    assert "True" in msg


def test_compare_undetermined_when_missing_from_base() -> None:
    base = "theorem unrelated : 1 = 1 := rfl\n"
    head = "theorem one_add_one : (1 : Nat) + 1 = 2 := rfl\n"
    verdict, msg = compare(base, head, "one_add_one")
    assert verdict == Verdict.UNDETERMINED
    assert "base" in msg


def test_compare_undetermined_when_missing_from_head() -> None:
    head = "theorem unrelated : 1 = 1 := rfl\n"
    verdict, msg = compare(_BASE, head, "one_add_one")
    assert verdict == Verdict.UNDETERMINED
    assert "head" in msg


def test_compare_equivalent_ignoring_whitespace_only_reformat() -> None:
    head = "theorem one_add_one :\n    (1 : Nat) + 1 = 2 := rfl\n"
    verdict, _ = compare(_BASE, head, "one_add_one")
    assert verdict == Verdict.EQUIVALENT


# ---------------------------------------------------------------------------
# Per-prover: weakened-statement detection
# ---------------------------------------------------------------------------

_ROCQ_TWO_VARS = (
    "Theorem add_comm_ex : forall a b : nat, a + b = b + a.\n"
    "Proof. intros. apply Nat.add_comm. Qed.\n"
)
_ROCQ_ONE_VAR = (
    "Theorem add_comm_ex : forall a : nat, a + a = a + a.\n"
    "Proof. reflexivity. Qed.\n"
)


def test_rocq_compare_changed_when_statement_weakened() -> None:
    # `forall a b : nat` (two universally-quantified variables) weakened
    # to `forall a : nat` (one) — the sibling statement is a strictly
    # weaker claim smuggled in under the same declaration name.
    verdict, msg = compare(_ROCQ_TWO_VARS, _ROCQ_ONE_VAR, "add_comm_ex", profile=ROCQ)
    assert verdict == Verdict.CHANGED
    assert "differs" in msg


def test_isabelle_compare_changed_when_statement_weakened() -> None:
    base = 'lemma add_comm_nat:\n  "a + b = b + (a::nat)"\n  by simp\n'
    head = 'lemma add_comm_nat:\n  "a = a"\n  by simp\n'
    verdict, msg = compare(base, head, "add_comm_nat", profile=ISABELLE)
    assert verdict == Verdict.CHANGED
    assert "differs" in msg
