"""Standing in a project folder should be the whole input.

Everything the pipeline needs is already there — git knows the checkout
root, the remote knows the slug, `.choir/project.toml` knows the prover —
so `choir orch viz` takes no required arguments. These tests cover the
discovery, because a wrong slug or a wrong root is the failure that makes
the command useless without making it error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from viz.report import ReportError, discover


def _repo(tmp_path: Path, *, remotes: dict[str, str], prover: str = "") -> Path:
    root = tmp_path / "proj"
    (root / "sub" / "deeper").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "remote", "add", name, url], cwd=root, check=True)
    if prover:
        (root / ".choir").mkdir()
        (root / ".choir" / "project.toml").write_text(
            f'[project]\nprover = "{prover}"\n', encoding="utf-8"
        )
    return root


def test_the_folder_supplies_the_slug_the_root_and_the_prover(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        remotes={"origin": "git@github.com:owner/proj.git"},
        prover="isabelle",
    )
    found = discover(root / "sub" / "deeper")
    assert found.repo == "owner/proj"
    assert found.checkout == root.resolve()   # the root, not where you stood
    assert found.prover == "isabelle"


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:owner/proj.git",
        "https://github.com/owner/proj.git",
        "https://github.com/owner/proj",
        "ssh://git@github.com/owner/proj.git",
    ],
)
def test_every_remote_spelling_git_uses(tmp_path: Path, url: str) -> None:
    root = _repo(tmp_path, remotes={"origin": url})
    assert discover(root).repo == "owner/proj"


def test_a_named_upstream_wins_over_origin(tmp_path: Path) -> None:
    """In a contributor's clone `origin` is their fork.

    The timeline belongs to the upstream project, so a fork's own history
    is the wrong answer — and it is the answer that looks right, because
    the fork does have the branches.
    """
    root = _repo(
        tmp_path,
        remotes={
            "origin": "git@github.com:contributor/proj.git",
            "upstream": "git@github.com:owner/proj.git",
        },
    )
    assert discover(root).repo == "owner/proj"


def test_a_missing_prover_falls_back_rather_than_failing(tmp_path: Path) -> None:
    """A picture of the wrong prover's declarations is recoverable.

    A tool that refuses to run is not.
    """
    root = _repo(tmp_path, remotes={"origin": "git@github.com:owner/proj.git"})
    assert discover(root).prover == "lean4"


def test_no_recognisable_remote_says_so(tmp_path: Path) -> None:
    root = _repo(tmp_path, remotes={"origin": "/some/local/path"})
    with pytest.raises(ReportError, match="no GitHub remote"):
        discover(root)
