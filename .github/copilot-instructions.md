# Copilot instructions for Choir

[`AGENTS.md`](../AGENTS.md) at the repository root is the contributor guide —
architecture, roles, layout, and the full list of non-negotiables. Read it
before changing code. This file exists for the Copilot surfaces that do not
load `AGENTS.md` (Copilot Chat on GitHub.com, for one), and repeats only what
is costly to get wrong.

## Build, lint, test

- Python 3.11+, managed with `uv`. `uv sync --extra dev` once.
- `uv run ruff check .` before every commit.
- `uv run pytest` for the suite; it deselects the `slow` marker, which needs a
  real Lean or Isabelle toolchain. Run `uv run pytest -m slow` before changing
  anything under `gate/provers/` or `gate/verify/`.
- Type hints on new code, and `from __future__ import annotations` at the top
  of modules.

## Invariants a change must not break

- **No merge path bypasses the gate.** Every PR clears the clean-room rebuild,
  statement identity, statement immutability, axiom honesty, and sorry-delta
  checks — including the orchestrator's own `merge_pr`, at every automation
  level.
- **Never proxy LLM credentials.** Choir must not see, store, or forward a
  contributor's keys; their agent runs on their hardware and their account.
- **The dependency rule.** `gate/` imports neither `orchestrator/` nor
  `client/`; those two depend on `gate/` and never on each other.
- **`PROTOCOL_VERSION` is a wire contract.** Bump it only when the parties'
  agreement changes, never for a refactor. If
  `tests/gate/test_protocol_fingerprint.py` fails, decide whether the change is
  compatible before regenerating the snapshot.
- **Apache-2.0 or MIT only** for anything vendored into the tree.

## Things that read as bugs but are not

- `merge-override` is a separate subcommand rather than a flag so an allowlist
  can deny it by name. Don't fold it into `merge`.
- Latency tolerance is deliberate: Actions cold starts take minutes and
  contributor agents go offline for hours. Don't add tight wait loops.
