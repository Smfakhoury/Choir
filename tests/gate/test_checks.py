"""Canonical gate check registry (spec 2026-08-17, reduced taxonomy)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from gate.checks import (
    BRANCH_PROTECTION_CONTEXTS,
    CHECK_WORKFLOW_TEMPLATES,
    CHECKS,
    PROVER_OVERRIDES,
    REQUIRED_PRESENT,
    CheckClass,
    check_class,
    is_blocking,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_PROJECT = REPO_ROOT / "scripts" / "new-project.sh"
UPGRADE_PROJECT = REPO_ROOT / "scripts" / "upgrade-project.sh"
TEMPLATES_DIR = REPO_ROOT / "templates" / "workflows"

# The module a workflow's `run:` step drives, e.g. `uv run python -m
# gate.verify.sorry_delta_cli`.
_RUN_MODULE_RE = re.compile(r"-m\s+(gate\.[\w.]+)")
# `gh <resource>` as the CLIs spell it: the tool named first in a shared
# runner (`_run("gh", "issue", ...)`), or a module-local wrapper that
# supplies it (`_gh("pr", ...)`, possibly with the arguments wrapped
# onto the next line).
_GH_CALL_RE = re.compile(r'(?:"gh"\s*,|_gh\()\s*"(\w+)"')
# Which workflow permission scope each `gh` resource needs.
_GH_RESOURCE_SCOPES = {"issue": "issues", "pr": "pull-requests"}


def test_advisory_checks_do_not_block() -> None:
    assert not is_blocking("style")
    assert not is_blocking("trust-report")
    assert not is_blocking("review")


def test_unknown_checks_block_fail_safe() -> None:
    assert is_blocking("some-future-check")


def _new_project_contexts() -> list[str]:
    """The `contexts` array literal from `scripts/new-project.sh`'s branch-
    protection JSON, parsed the same way both drift-guard tests below need."""
    text = NEW_PROJECT.read_text(encoding="utf-8")
    block = re.search(r'"contexts":\s*\[(.*?)\]', text, re.DOTALL)
    assert block, "could not find the contexts array in new-project.sh"
    contexts = re.findall(r'"([^"]+)"', block.group(1))
    assert contexts, "contexts array parsed as empty"
    return contexts


def test_every_required_context_is_registered() -> None:
    """The drift guard: the bug this registry exists to prevent.

    `review` was added to new-project.sh's required contexts and never to
    the salvage classifier's sets, so every red PR misclassified. Any name
    in the contexts array must be known here.
    """
    contexts = _new_project_contexts()
    unregistered = [c for c in contexts if c not in CHECKS]
    assert not unregistered, f"unregistered required contexts: {unregistered}"


def _new_project_workflow_copies() -> list[str]:
    """The `PY_WORKFLOWS=(...)` array from `new-project.sh`.

    Was a literal `for w in …; do cp` list until the overlay manifest
    (2026-08-28) needed the same names a second time, to declare them as
    the managed overlay set. Rather than keep two copies in one script, the
    list became an array both loops iterate.
    """
    text = NEW_PROJECT.read_text(encoding="utf-8")
    block = re.search(r"PY_WORKFLOWS=\((.*?)\)", text, re.DOTALL)
    assert block, "could not find new-project.sh's PY_WORKFLOWS array"
    names = block.group(1).replace("\\", " ").split()
    assert names, "new-project.sh's PY_WORKFLOWS array parsed as empty"
    return names


def _upgrade_project_workflow_copies() -> list[str]:
    """The `PY_WORKFLOWS=(...)` array from `upgrade-project.sh`."""
    text = UPGRADE_PROJECT.read_text(encoding="utf-8")
    block = re.search(r"PY_WORKFLOWS=\((.*?)\)", text, re.DOTALL)
    assert block, "could not find upgrade-project.sh's PY_WORKFLOWS array"
    names = block.group(1).replace("\\", " ").split()
    assert names, "upgrade-project.sh's PY_WORKFLOWS array parsed as empty"
    return names


def test_check_workflow_templates_cover_every_registered_check() -> None:
    """Every name in `CHECKS` must have an entry in `CHECK_WORKFLOW_TEMPLATES`
    — generated-inline (`None`) or a real template — so a future check
    added to one and forgotten in the other is caught here rather than
    discovered by a bricked bootstrap."""
    assert set(CHECK_WORKFLOW_TEMPLATES) == set(CHECKS)


def test_required_present_workflow_templates_are_copied_by_both_scripts() -> None:
    """F1 (2026-08-20 review): nothing previously pinned that the scripts
    actually *install* the workflow behind a required check. The two
    guards above only ever compared `REQUIRED_PRESENT` against
    `new-project.sh`'s `contexts` string literal — never against the
    scripts' `for w in ...` / `PY_WORKFLOWS=(...)` copy lists or the
    filesystem. A dropped or misspelled entry in either copy list would
    ship green today and brick every merge on a freshly bootstrapped or
    upgraded project: the workflow never runs, so the required check is
    absent rather than failing, and `merge_pr`'s preflight treats an
    absent required check as a bypass attempt.

    The mapping is not 1:1 (`sorry-delta` -> `verify-sorry.yml`), and a
    `rebuild`-style check has no template to check at all — both handled
    by `CHECK_WORKFLOW_TEMPLATES`, which is the one place that fact lives.
    """
    new_project_copies = set(_new_project_workflow_copies())
    upgrade_project_copies = set(_upgrade_project_workflow_copies())
    for name in REQUIRED_PRESENT:
        template = CHECK_WORKFLOW_TEMPLATES[name]
        if template is None:
            continue  # generated inline (e.g. rebuild -> verify-pr.yml); nothing to check
        assert (TEMPLATES_DIR / template).is_file(), (
            f"{name}: template {template} missing from templates/workflows/"
        )
        stem = template.removesuffix(".yml")
        assert stem in new_project_copies, (
            f"{name}: {stem} missing from new-project.sh's workflow-copy list"
        )
        assert stem in upgrade_project_copies, (
            f"{name}: {stem} missing from upgrade-project.sh's PY_WORKFLOWS array"
        )


def test_every_cli_gh_resource_is_permitted_by_its_workflow_template() -> None:
    """A workflow that declares a `permissions:` block gets `none` for
    every scope it does not list, so a `gh` call against an unlisted
    resource fails with 403 at runtime — on every pull request, not just
    an unlucky one. This pairs each template's permission scopes against
    the `gh` resources of the CLI module its `run:` steps invoke, so a
    CLI that starts reading a new resource fails here rather than in CI
    on someone's submission.

    A resource with no entry in `_GH_RESOURCE_SCOPES` fails too: the
    scope a new `gh` resource needs is a fact to record here, not to
    guess at.
    """
    pairs: list[tuple[str, str, str]] = []
    for path in sorted(TEMPLATES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        scopes = set(doc.get("permissions") or {})
        modules = {
            module
            for job in doc.get("jobs", {}).values()
            for step in job.get("steps", [])
            if isinstance(step.get("run"), str)
            for module in _RUN_MODULE_RE.findall(step["run"])
        }
        for module in sorted(modules):
            source = REPO_ROOT / (module.replace(".", "/") + ".py")
            assert source.is_file(), f"{path.name} runs {module}, which has no source"
            for resource in sorted(set(_GH_CALL_RE.findall(source.read_text("utf-8")))):
                scope = _GH_RESOURCE_SCOPES.get(resource)
                assert scope is not None, (
                    f"{module} calls `gh {resource}`, which this guard has no "
                    "permission scope for — add it to _GH_RESOURCE_SCOPES"
                )
                assert scope in scopes, (
                    f"{path.name} runs {module}, which calls `gh {resource}`, "
                    f"but its permissions block does not grant `{scope}` — an "
                    "unlisted scope is `none`, so that call 403s on every PR"
                )
                pairs.append((path.name, module, resource))
    assert pairs, (
        "no `gh` calls found in any workflow's CLI — `_GH_CALL_RE` no longer "
        "matches how they are spelled, so this guard is asserting nothing"
    )


def test_no_workflow_template_run_block_interpolates_untrusted_input() -> None:
    """A `run:` script is textually substituted by the Actions runner before
    the shell ever sees it, so any templater expression spliced into one is
    substitution, not shell input. Two spellings of that mistake are
    guarded here: a `run:` step that interpolates the submitter-controlled
    PR body directly (a body ending in a shell metacharacter becomes shell
    input), and a `run:` step that reads an `env:` entry as `${{ env.FOO
    }}` instead of `"$FOO"` — the templater still splices that in before
    the shell runs, so it is exactly as unsafe as the first spelling even
    though the value now passes through an `env:` mapping. The safe form
    reads an `env:` entry back with the shell's own `"$VAR"`, which the
    shell expands, not the templater. This guards against either spelling
    of the same mistake reappearing.
    """
    unsafe_expr = "github.event.pull_request.body"
    unsafe_env_ref = "${{ env."
    for path in sorted(TEMPLATES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in doc.get("jobs", {}).values():
            for step in job.get("steps", []):
                run = step.get("run")
                if isinstance(run, str):
                    assert unsafe_expr not in run, (
                        f"{path.name}: a `run:` step interpolates the PR "
                        "body directly — route it through `env:` instead"
                    )
                    assert unsafe_env_ref not in run, (
                        f"{path.name}: a `run:` step splices an `env:` "
                        'value through the templater — read it back as '
                        '"$VAR" instead, which the shell expands'
                    )


def test_composite_workflow_slash_job_names_resolve() -> None:
    """gh may report "workflow / job"; the trailing segment is the job name."""
    assert not is_blocking("verify-style / style")
    assert is_blocking("verify-pr / rebuild")


def test_statement_equiv_is_advisory_on_lean4_only() -> None:
    """comparator supersedes it on lean4; nothing does on the others."""
    assert not is_blocking("statement-equiv", prover="lean4")
    assert is_blocking("statement-equiv", prover="isabelle")
    assert is_blocking("statement-equiv", prover="rocq")


def test_omitting_the_prover_gives_the_strict_answer() -> None:
    """A caller that forgets the prover must not silently un-gate a check."""
    assert is_blocking("statement-equiv")
    assert check_class("statement-equiv") is CheckClass.TRUST


def test_unknown_prover_falls_back_to_the_base_class() -> None:
    assert is_blocking("statement-equiv", prover="agda")


def test_overrides_only_ever_relax() -> None:
    """Structural guard: an override may not be stricter than the base.

    A stricter override would mean a caller omitting the prover gets the
    weaker answer — the exact fail-open this design exists to prevent.

    Ranks TRUST strictly above QUALITY (spec 2026-08-20, finding F3): an
    earlier version of this guard collapsed `{ADVISORY: 0, QUALITY: 1,
    TRUST: 1}`, which cannot see either a QUALITY→TRUST tightening (a real
    tightening — it would kill salvage for that check on that prover) or a
    TRUST→QUALITY override (still merge-blocking, but before F1's salvage
    reversal would have turned a trust failure into an auto-seeded
    NEAR_MISS). The separate assertion below closes the QUALITY→TRUST case
    directly: a QUALITY base must never be overridden at all, so there is no
    way to introduce that tightening even by construction.
    """
    rank = {CheckClass.ADVISORY: 0, CheckClass.QUALITY: 1, CheckClass.TRUST: 2}
    for prover, overrides in PROVER_OVERRIDES.items():
        for name, cls in overrides.items():
            assert name in CHECKS, f"{prover} overrides unregistered {name}"
            assert rank[cls] <= rank[CHECKS[name]], (
                f"{prover}'s override of {name} is stricter than the base"
            )
            assert CHECKS[name] is not CheckClass.QUALITY, (
                f"{prover} overrides {name}, whose base class is QUALITY — "
                "a QUALITY base must never be overridden at all, so it can "
                "never be tightened to TRUST"
            )


def test_branch_protection_contexts_matches_new_project_literal() -> None:
    """One source of truth for the required-contexts array.

    The array previously lived only as a literal in new-project.sh, with this
    file asserting a *subset* relation against REQUIRED_PRESENT. That left the
    direction a subset check cannot see: a context in the script that Choir no
    longer requires. Equality closes it, and gives upgrade-project.sh's
    staleness report something to compare a live repo against.
    """
    assert _new_project_contexts() == list(BRANCH_PROTECTION_CONTEXTS)


def test_required_present_is_a_subset_of_protection_contexts() -> None:
    """Every check the merge preflight demands be PRESENT must also be one
    GitHub is told to require, or `missing_required` can never fire."""
    missing = [n for n in REQUIRED_PRESENT if n not in BRANCH_PROTECTION_CONTEXTS]
    assert not missing, f"REQUIRED_PRESENT names absent from contexts: {missing}"


def _manifest_declared_paths(script: Path) -> list[str]:
    """The paths a bootstrap script declares to `gate.upgrade.manifest`.

    Reads the `MANIFEST_ARGS+=(...)` appends, taking both the literal paths
    and the `.github/workflows/$w.yml` loop form, so the guard below reads
    the same source of truth the script actually passes to the CLI.
    """
    text = script.read_text(encoding="utf-8")
    paths: list[str] = []
    for block in re.findall(r"MANIFEST_ARGS\+=\((.*?)\)", text, re.DOTALL):
        paths.extend(re.findall(r'--(?:managed|seeded)\s+"?([^"\s]+)"?', block))
    return paths


def test_both_scripts_declare_their_workflow_loop_to_the_manifest() -> None:
    """A workflow copied but not declared is invisible to retirement.

    `gate/upgrade/manifest.py` derives retirement from the difference
    between two declared overlay sets, so a template installed but never
    declared would never be retired later — and would be reported as
    `unmanaged` on a seed run of the very repo that installed it. Both
    scripts declare the loop variable rather than a second literal list, so
    this asserts the loop form is present; the array's *contents* are
    guarded by `test_required_present_workflow_templates_are_copied_by_both_scripts`.
    """
    for script in (NEW_PROJECT, UPGRADE_PROJECT):
        declared = _manifest_declared_paths(script)
        assert declared, f"{script.name} declares nothing to the manifest"
        assert any(
            "workflows/$w.yml" in path for path in declared
        ), f"{script.name} does not declare its workflow-copy loop to the manifest"


def test_both_scripts_declare_the_two_conditionally_written_files() -> None:
    """verify-pr.yml and .choir/verify.toml are written at bootstrap and left
    alone by every later upgrade, so they must be declared on EVERY run.

    Declaring only what a run wrote would put them outside the overlay set on
    every upgrade, and the retirement diff would report them retired forever.
    """
    for script in (NEW_PROJECT, UPGRADE_PROJECT):
        declared = _manifest_declared_paths(script)
        for path in (".github/workflows/verify-pr.yml", ".choir/verify.toml"):
            assert path in declared, f"{script.name} does not declare {path}"


def test_both_scripts_declare_the_lean4_only_trust_report() -> None:
    """Prover-conditional, but still declared: the CLI omits a declared path
    that is absent on disk, so declaring it on isabelle/rocq is harmless while
    forgetting it on lean4 would leave the file unretirable."""
    for script in (NEW_PROJECT, UPGRADE_PROJECT):
        declared = _manifest_declared_paths(script)
        assert ".github/workflows/verify-trust-report.yml" in declared, (
            f"{script.name} does not declare verify-trust-report.yml"
        )
