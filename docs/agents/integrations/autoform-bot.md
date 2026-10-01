# AutoformBot on Choir

[AutoformBot](https://github.com/facebookresearch/autoform-bot) plans a
formalization as a Markdown blueprint and proves it with local agents. On
Choir it plans and writes statements on the overseer's machine and proves on
contributors' machines, and Choir carries every task between them. Use
AutoformBot's skills as they are; this note covers only where the two tools
meet. Its worker and specialist agents ship with its `execution` overlay.

`$AUTOFORM` is AutoformBot's plugin root. Its CLI runs as
`uv run --project "$AUTOFORM" autoform …` from the project checkout.

## Overseer

### Setup

After Choir's bootstrap, add AutoformBot's layer with `autoform init`, as its
`setup` skill says. Then:

- Add `site/`, `site-src/` and `*.log` to `.gitignore`; `init` leaves Choir's
  alone.
- **Delete the `pull_request:` trigger from `autoform-verify.yml` and
  `blueprint-pages.yml` before you push.** The audit rejects `sorryAx`, which a
  Choir project always holds for its open tasks, and the Pages `deploy` job is
  skipped on pull requests. The merge preflight treats any check it doesn't
  recognise as blocking until it succeeds, so either would block every merge.
- **Never create a `roadmap/` directory at the project root.** AutoformBot
  rejects a directory holding both `roadmap/` and `blueprint/roadmap/`, so its
  tools stop working there and in every workspace pinned to such a commit.
  Keep your reasoning log in `reasoning-log.md` instead.

### The plan

The blueprint, built with AutoformBot's `roadmap` skill, is the plan.
`orchestrator-planning.md` from § Decomposition guidance on still applies:
read "node" as an article, and `uses` and `proof_uses` as its
`## Depends on` and `## Proof depends on`.

### Statements

You write every statement, using AutoformBot's statement work on this machine;
its claims work here because you have write access. Run its `content-reviewer`
and `counterexample-hunter` on each statement before you commit it: a published
statement is frozen, so a wrong one costs a republish. Commit each declaration
with a `sorry` body, set `statement: formalized` and `lean:` on its article,
and push. Don't run AutoformBot's proof phase on work you publish.

### Publishing

A node is ready when AutoformBot reports it `can_prove` and not yet proved:

```bash
uv run --project "$AUTOFORM" python - <<'EOF'
import json
from autoform_cli.runtime import load_runtime_graph
graph = load_runtime_graph(".", lean_root=".")
for node in graph.nodes:
    if (node.dispatchable and node.status.can_prove and not node.status.proved
            and not node.assertions.not_ready):
        print(json.dumps({"id": node.id, "article": node.article_path,
                          "targets": [t.as_dict() for t in node.lean_targets]}))
EOF
```

Skip a node with an open task (`choir orch tasks --state open` shows each
task's `blueprint_ref`). Publish one task per declaration still holding a
placeholder: `--target-file` and `--target-decl` from `targets`,
`--blueprint-ref` set to the node id, and the article's path in `--prose`.
Then set `discussion: <issue number>` on the article; it follows the article if
the article moves, which the path-derived node id doesn't.

### The loop

- **Each pass:** `autoform check blueprint --lean-root .` and
  `autoform audit blueprint --lean-root .` replace `sync-graph`.
- **Review:** use AutoformBot's `agent-review` rubrics in § Stage two.
- **After a merge:** set `proof: formalized` once every declaration the article
  names is proved, then publish what became ready.
- **A reduction:** each child becomes an article beside its parent
  (`origin: bridged`, `statement: formalized`, `lean: <child>`), linked from
  the parent's `## Proof depends on`. A worker wrote these statements, so run
  `content-reviewer` on each before you accept.

## Contributor

In § 3. Prove it, hand the task to AutoformBot's `autoform-worker` agent and
act as its parent:

- **Project:** `prepared.path`. **Article:** the path `TASK.md` names.
  **Target:** `target_file` and `target_decl` from `prepared.record`.
- **Claim:** your Choir lease. Don't run `autoform claim` or take its
  `lake-build` claim; `choir worker heartbeat` is the renewal it expects.
- **Tell it:** edit only the target file, not the article, and never touch a
  statement.

Its `PROVED` or `FAILED` report is the report § 3 asks for. A refutation from
`counterexample-hunter` is a "this statement is wrong" `choir-defect`.
