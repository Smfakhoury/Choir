"""Tests for `gate.provers.fstar` — the F*/Pulse profile, its statement
extractor, and its trust-report probe (design note 12 §2.2, §3.2).

One profile covers both languages: Pulse is not a separate prover but a
`#lang-pulse` block inside an ordinary `.fst` file, so the extractor has
to handle `fn` alongside `val`/`let`.

The probe tests carry the most weight here. Two bugs in that path were
found only by running the real binary, and both were invisible to
unit-level reasoning about the profile:

- the `(targets, imports)` contract was misread as (paths, include
  dirs), so the probe failed for every declaration; and
- a `.checked` cache silently suppressed every finding, which turns a
  missing proof into a passing report.

Each has a named regression test below.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gate.provers import PROFILES
from gate.provers.fstar import (
    FSTAR,
    _probe_is_project_location,
    _resolve_probe_sources,
    extract_fstar_statement,
    fstar_trust_report_command,
    parse_fstar_trust_report,
)
from gate.verify.axiom_honesty import Verdict as AxiomVerdict
from gate.verify.axiom_honesty import compare as compare_axioms
from gate.verify.statement_immutability import Verdict, compare_declarations

_FSTAR_AVAILABLE = shutil.which("fstar.exe") is not None

# An ordinary F* module: a `val`/`let` pair per lemma, which is the
# shape the placeholder filler is pointed at.
FSTAR_SRC = """
module Demo.Clrs

val add_comm (a b : nat) : Lemma (ensures a + b == b + a)
let add_comm a b = ()

val add_assoc (a b c : nat) : Lemma (ensures (a + b) + c == a + (b + c))
let add_assoc a b c = admit ()
"""

# Pulse, including an instance binder — `{| d : dict a |}` is easy to
# truncate a statement on, so it is pinned explicitly.
PULSE_SRC = """
module Demo.Pulse
#lang-pulse

fn lookup (#a : Type) {| d : dict a |} (m : map a) (k : key)
  requires is_map m
  ensures  fun r -> is_map m /\\ found r
{
  admit()
}
"""


def test_profile_is_registered_under_fstar() -> None:
    assert PROFILES["fstar"] is FSTAR
    assert FSTAR.name == "fstar"


def test_placeholder_tokens_cover_admit_and_magic() -> None:
    assert set(FSTAR.placeholder_tokens) == {"admit", "magic"}


def test_trust_patterns_watch_the_escape_hatches() -> None:
    labels = {name for name, _ in FSTAR.trust_patterns}
    assert {"assume", "admit", "magic", "tactic_admit", "admit_option"} <= labels


def test_extract_statement_keeps_the_val_signature() -> None:
    statement = extract_fstar_statement(FSTAR_SRC, "add_comm")
    assert statement is not None
    assert "ensures a + b == b + a" in statement
    # The proof term must not leak into the statement, or a worker
    # could edit the obligation and still compare equal.
    assert "let add_comm" not in statement


def test_extract_statement_retains_pulse_instance_binder() -> None:
    statement = extract_fstar_statement(PULSE_SRC, "lookup")
    assert statement is not None
    assert "{| d : dict a |}" in statement
    assert "requires is_map m" in statement
    assert "ensures" in statement


def test_honest_fill_leaves_the_statement_unchanged() -> None:
    head = FSTAR_SRC.replace("let add_assoc a b c = admit ()", "let add_assoc a b c = ()")
    verdict, _ = compare_declarations(FSTAR_SRC, head, profile=FSTAR)
    assert verdict is Verdict.UNCHANGED


def test_weakened_ensures_is_caught() -> None:
    head = FSTAR_SRC.replace(
        "val add_assoc (a b c : nat) : Lemma (ensures (a + b) + c == a + (b + c))",
        "val add_assoc (a b c : nat) : Lemma (ensures True)",
    )
    verdict, _ = compare_declarations(FSTAR_SRC, head, profile=FSTAR)
    assert verdict is Verdict.CHANGED


@pytest.mark.parametrize(
    "proof",
    [
        "assert (True) by (FStar.Tactics.tadmit ())",
        "magic ()",
        "admit1 ()",
    ],
)
def test_axiom_honesty_flags_introduced_escape_hatches(proof: str) -> None:
    base = FSTAR_SRC.replace("let add_assoc a b c = admit ()", "let add_assoc a b c = ()")
    head = base.replace("let add_assoc a b c = ()", f"let add_assoc a b c = {proof}")
    verdict, findings = compare_axioms(base, head, profile=FSTAR)
    assert verdict is AxiomVerdict.INTRODUCED, findings


def test_axiom_honesty_flags_assume_val() -> None:
    base = FSTAR_SRC.replace("let add_assoc a b c = admit ()", "let add_assoc a b c = ()")
    head = base.replace(
        "val add_assoc",
        "assume val cheat : unit -> Lemma (ensures False)\n\nval add_assoc",
    )
    verdict, _ = compare_axioms(base, head, profile=FSTAR)
    assert verdict is AxiomVerdict.INTRODUCED


def test_parse_dedups_the_doubled_warnings() -> None:
    # F* prints each `--report_assumes` warning twice; the parser keys
    # on (location, name) so the report lists each site once.
    raw = (
        "* Warning 335 at Demo.Clrs.fst(7,22-7,27):\n"
        "  - Every use of Prims.admit triggers a warning\n"
        "  - Uses an axiom\n"
    ) * 2
    entries = parse_fstar_trust_report(raw)
    assert len(entries) == 1
    assert entries[0].decl == "Demo.Clrs.fst(7,22-7,27)"
    assert entries[0].assumptions == ("Prims.admit",)
    assert entries[0].clean is False


def test_parse_reads_the_option_form() -> None:
    raw = (
        "* Warning 335 at Demo.Clrs.fst(6,0-6,40):\n"
        "  - Every use of this option triggers a warning: admit_smt_queries\n"
    )
    entries = parse_fstar_trust_report(raw)
    assert [e.assumptions for e in entries] == [("option:admit_smt_queries",)]


def test_parse_drops_standard_library_findings() -> None:
    # `--cache_off` re-elaborates ulib too, so its own internal admit
    # shows up. It is absolute-pathed; the project's files are not.
    raw = (
        "* Warning 335 at /opt/fstar/lib/fstar/ulib/Prims.fst(444,2-444,7):\n"
        "  - Every use of Prims.admit triggers a warning\n"
        "* Warning 335 at Demo.Clrs.fst(7,22-7,27):\n"
        "  - Every use of Prims.admit triggers a warning\n"
    )
    entries = parse_fstar_trust_report(raw)
    assert [e.decl for e in entries] == ["Demo.Clrs.fst(7,22-7,27)"]


def test_project_location_predicate() -> None:
    assert _probe_is_project_location("Demo/Clrs.fst(1,0-1,2)")
    assert not _probe_is_project_location("/usr/lib/fstar/ulib/Prims.fst(444,2-444,7)")


def test_parse_reads_the_tactic_admit_code() -> None:
    raw = "* Warning 296 at Demo.Clrs.fst(7,22-7,27):\n  - Tactics admitted goal\n"
    entries = parse_fstar_trust_report(raw)
    assert [e.assumptions for e in entries] == [("tactic:admitted_goal",)]


class TestProbeCommand:
    """The two bugs the real binary exposed, pinned."""

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / "Demo").mkdir()
        (tmp_path / "Demo" / "Demo.Clrs.fst").write_text(FSTAR_SRC)
        return tmp_path

    def test_resolves_a_module_name_to_its_source_file(self, tmp_path: Path) -> None:
        # Regression: `targets` are declaration names and `imports` are
        # module names. Treating a target as a path made F* reject the
        # declaration name as a filename for every target.
        workspace = self._workspace(tmp_path)
        sources = _resolve_probe_sources(workspace, ["add_assoc"], ["Demo.Clrs"])
        assert [p.name for p in sources] == ["Demo.Clrs.fst"]

    def test_command_passes_the_file_not_the_decl_name(self, tmp_path: Path) -> None:
        workspace = self._workspace(tmp_path)
        argv = fstar_trust_report_command(workspace, ["add_assoc"], ["Demo.Clrs"])
        # The profile wraps the call in `sh -c "... 2>&1"` because the
        # warnings go to stderr and the shared probe returns stdout.
        assert argv[:2] == ["sh", "-c"]
        assert "Demo.Clrs.fst" in argv[2]
        assert "add_assoc" not in argv[2]

    def test_interface_is_preferred_over_implementation(self, tmp_path: Path) -> None:
        # A `val` in a `.fsti` is where an `assume` would hide.
        workspace = self._workspace(tmp_path)
        interface = workspace / "Demo" / "Demo.Clrs.fsti"
        interface.write_text("module Demo.Clrs\nval add_comm : unit\n")
        sources = _resolve_probe_sources(workspace, ["add_comm"], ["Demo.Clrs"])
        assert [p.suffix for p in sources] == [".fsti"]

    def test_a_direct_file_target_still_works(self, tmp_path: Path) -> None:
        workspace = self._workspace(tmp_path)
        sources = _resolve_probe_sources(workspace, ["Demo/Demo.Clrs.fst"], [])
        assert [p.name for p in sources] == ["Demo.Clrs.fst"]

    def test_unresolvable_module_raises_rather_than_reporting_clean(
        self, tmp_path: Path
    ) -> None:
        # Failing loudly matters: an empty command would be read as a
        # clean trust report.
        from gate.provers import ProverError

        workspace = self._workspace(tmp_path)
        with pytest.raises(ProverError):
            fstar_trust_report_command(workspace, ["nope"], ["No.Such.Module"])

    def test_probe_disables_the_cache_entirely(self, tmp_path: Path) -> None:
        # Regression: if F* loads a `.checked` file it does not
        # re-elaborate, so `--report_assumes` reports nothing and an
        # admitted proof reads as clean. A scratch `--cache_dir` is
        # not enough -- F* still picks up a `.checked` beside the
        # source -- so the cache has to be off.
        workspace = self._workspace(tmp_path)
        argv = fstar_trust_report_command(workspace, ["add_assoc"], ["Demo.Clrs"])
        assert "--cache_off" in argv[2]

    def test_source_path_is_relative_to_the_workspace(self, tmp_path: Path) -> None:
        # Load-bearing: the probe runs with `cwd=workspace`, and the
        # relative/absolute split is what distinguishes the project's
        # findings from the standard library's.
        workspace = self._workspace(tmp_path)
        argv = fstar_trust_report_command(workspace, ["add_assoc"], ["Demo.Clrs"])
        assert str(workspace) not in argv[2]


@pytest.mark.skipif(not _FSTAR_AVAILABLE, reason="fstar.exe not on PATH")
class TestAgainstTheRealBinary:
    @staticmethod
    def _warm(tmp_path: Path, *extra: str) -> Path:
        (tmp_path / "Demo").mkdir()
        source = tmp_path / "Demo" / "Demo.Clrs.fst"
        source.write_text(FSTAR_SRC)
        warm = subprocess.run(
            ["fstar.exe", "--cache_checked_modules", *extra, str(source)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert warm.returncode == 0, warm.stderr
        return source

    def test_reports_the_admit_despite_a_colocated_checked_file(
        self, tmp_path: Path
    ) -> None:
        """The soundness property `--cache_off` buys.

        A `.checked` file beside the source is read whatever
        `--cache_dir` says, so this is the case a scratch cache
        directory does not cover.
        """
        self._warm(tmp_path)
        assert list(tmp_path.glob("Demo/*.checked")), "cache did not warm; test is vacuous"

        argv = fstar_trust_report_command(tmp_path, ["add_assoc"], ["Demo.Clrs"])
        probed = subprocess.run(argv, capture_output=True, text=True, cwd=tmp_path)
        entries = parse_fstar_trust_report(probed.stdout)
        assert entries, f"cached module suppressed the report: {probed.stdout!r}"
        assert any(
            "admit" in assumption for entry in entries for assumption in entry.assumptions
        )

    def test_reports_the_admit_despite_a_warm_project_cache_dir(
        self, tmp_path: Path
    ) -> None:
        cache = tmp_path / ".cache"
        cache.mkdir()
        self._warm(tmp_path, "--cache_dir", str(cache))
        assert list(cache.glob("*.checked")), "cache did not warm; test is vacuous"

        argv = fstar_trust_report_command(tmp_path, ["add_assoc"], ["Demo.Clrs"])
        probed = subprocess.run(argv, capture_output=True, text=True, cwd=tmp_path)
        assert parse_fstar_trust_report(probed.stdout), probed.stdout

    def test_does_not_report_the_standard_library(self, tmp_path: Path) -> None:
        (tmp_path / "Demo").mkdir()
        (tmp_path / "Demo" / "Demo.Clrs.fst").write_text(FSTAR_SRC)
        argv = fstar_trust_report_command(tmp_path, ["add_assoc"], ["Demo.Clrs"])
        probed = subprocess.run(argv, capture_output=True, text=True, cwd=tmp_path)
        assert "Prims.fst" in probed.stdout, "expected ulib to be re-elaborated"
        entries = parse_fstar_trust_report(probed.stdout)
        assert all("Prims.fst" not in entry.decl for entry in entries)

    def test_probe_leaves_no_artifacts_in_the_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "Demo").mkdir()
        (tmp_path / "Demo" / "Demo.Clrs.fst").write_text(FSTAR_SRC)
        argv = fstar_trust_report_command(tmp_path, ["add_assoc"], ["Demo.Clrs"])
        subprocess.run(argv, capture_output=True, text=True, cwd=tmp_path)
        assert not list(tmp_path.glob("**/*.checked"))
