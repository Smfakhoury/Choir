# AutoformBot on Choir

[AutoformBot](https://github.com/facebookresearch/autoform-bot) plans a
formalization as a Markdown blueprint and proves it with local specialist
agents. On Choir it keeps both jobs: the overseer's machine runs its planning
and statement work, contributors' machines run its proving agents, and Choir
carries every task between them. AutoformBot runs unmodified, at the commit
the project pins.

`$AUTOFORM` below is AutoformBot's plugin root, resolved the way its own
skills resolve it; its CLI runs as `uv run --project "$AUTOFORM" autoform …`
from the project checkout. The worker and specialist agents ship on its
`execution` branch, so pin a commit that has them.

## Overseer

Everything in `ORCHESTRATOR.md` holds. This section replaces the default plan
(`orchestrator-planning.md` § The roadmap) and names the steps AutoformBot
fills.

### Setup

Bootstrap with `new-project.sh` and run `orchestrator-init.sh` as
`orchestrator-setup.md` says, then add AutoformBot's layer from the project
checkout:

```bash
uv run --project "$AUTOFORM" autoform init . \
  --title "<title>" \
  --repository-url https://github.com/<owner/name> \
  --autoform-ref <full commit sha>
```

`--autoform-ref` is the 40-character commit the plugin was installed from.
Run from a Git checkout of AutoformBot, `init` reads it itself. Without one
it writes no CI, and AutoformBot's `setup` skill says how to find it.

That writes `blueprint/`, `mkdocs.yml`, `theme/`, `.github/autoform_audit.py`,
and two workflows: `autoform-verify.yml` and `blueprint-pages.yml`. It leaves
Choir's `README.md` and `.gitignore` alone, so add AutoformBot's ignore lines
yourself: `site/`, `site-src/` and `*.log`.

**Delete the `pull_request:` trigger from both workflows before you push.**
Neither can pass on a Choir pull request. `autoform-verify.yml` audits every
declaration in the project and rejects `sorryAx`, and a Choir project always
holds the placeholders of its published tasks. `blueprint-pages.yml` has a
`deploy` job that is skipped on every pull request. The merge preflight
counts any check it does not recognise as blocking until it succeeds, and a
skipped job never does. On pushes to main both keep working: the audit
reports whole-project trust, and the Pages job publishes the blueprint site
once Pages is enabled. The audit stays red while any placeholder remains,
and in a project with a recursive `def` it stays red after that too: it also
flags the `_unsafe_rec` helper Lean compiles for a recursive definition.
Read its log for anything else.

Commit and push to main. The Choir gate still runs on every pull request.

### The plan

The blueprint is the plan. Build it with AutoformBot's `roadmap` skill:
source notes under `blueprint/sources/`, the coverage table, a coarse roadmap
the overseer approves, then one article per pull-request-sized node. Review
it with `human-review` or `agent-review` before any statement is written.

`orchestrator-planning.md` from § Decomposition guidance on still applies.
Read its "node" as an article, and its `uses` and `proof_uses` as the
article's `## Depends on` and `## Proof depends on`.

Keep what `ORCHESTRATOR.md` § Your working memory asks of the log — your
reasoning log and the answer to the source question — in `reasoning-log.md`
at the project root, with a line pointing at `blueprint/`. The route and the
mathematics live in the blueprint and are not written twice.

**Never create a `roadmap/` directory at the project root.** AutoformBot
rejects a directory holding both `roadmap/` and `blueprint/roadmap/` as
ambiguous, so every AutoformBot tool given the project root stops working,
on your machine and in every workspace pinned to a commit that has it.

### Statements

You author every statement, as in any Choir project, and AutoformBot's
statement work runs on this machine with its own agents and claims. The
claims work here because you have write access. For each node whose
statement is next:

- Write the declaration with a `sorry` body. A definition gets its full body,
  since a shared definition is never a worker's to write.
- Check it against the source with `content-reviewer` and the faithfulness
  rubric. Try to refute it with `counterexample-hunter`, and check for an
  upstream result with `mathlib-checker`.
- Set `statement: formalized` and `lean: <declaration>` on the article.
  Leave `proof` unset.
- Push to main.

Do not run AutoformBot's proof phase for work you publish. Proofs are the
contributors'.

### Publishing

A node is ready when AutoformBot reports it `can_prove`: stated, and every
proof dependency proved. List the ready nodes from the project checkout:

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

Skip a node that already has an open task: `choir orch tasks --state open`
lists each task's `blueprint_ref`. Publish the rest, one task per declaration
still holding a placeholder:

```bash
choir orch --repo <owner/name> create-task \
    --title "prove <declaration>" \
    --target-file <source_file> --target-decl <declaration> \
    --commit <HEAD_SHA> --toolchain <TOOLCHAIN> \
    --blueprint-ref <node id> \
    --prose "Article: blueprint/roadmap/<article>. …what the article says, its sources, hints…"
```

Name the article's path in the prose: the worker's agent reads the article
first. Then set `discussion: <issue number>` on the article and push. The
node id in `blueprint_ref` is derived from the article's path, so it goes
stale if the article moves; the `discussion` field moves with the file.

Priority and difficulty labels work as `orchestrator-planning.md` says.

### Each pass

In `ORCHESTRATOR.md` § 1, the plan check is:

```bash
uv run --project "$AUTOFORM" autoform check blueprint --lean-root .
uv run --project "$AUTOFORM" autoform audit blueprint --lean-root .
```

`audit` exits nonzero whenever it has a finding, including a coverage row
still `MAPPED`. Read the findings rather than the exit code.

### Review

Run § Stage two with AutoformBot's `agent-review` rubrics as the subagent's
checklist: faithfulness for every statement the worker authored, proof
integrity, code quality, Mathlib style. The merge decision stays yours.

### After a merge

Set `proof: formalized` on the node's article once the last declaration it
names is proved, and push. That is the whole of § 3's plan update. Then run
the pass check and publish what became ready.

### A reduction

On accepting one (`orchestrator-review.md` § A reduction), write an article
beside the parent for each child: `declaration`, `origin: bridged`,
`statement: formalized`, `lean: <child>`. Link each from the parent's
`## Proof depends on`. The worker wrote these statements, so run
`content-reviewer` on each before you accept.

### A stuck task

Choir's struggle signal says when (`orchestrator-planning.md` § Stuck tasks).
AutoformBot says what: `counterexample-hunter` tries to refute the
statement, and `proof-strategy-researcher` proposes a route or a split. A
split becomes new articles through `roadmap`.

### Not used

`roadmap/graph.json`, `roadmap/<group>.md` and `choir orch sync-graph`.

## Contributor

Everything in `CONTRIBUTOR.md` holds. Install AutoformBot at the commit the
project pins; `AUTOFORM_REF` in the project's `autoform-verify.yml` names it.

In § 3. Prove it, hand the task to AutoformBot's `autoform-worker` agent. It
expects its parent to supply the following, and you are the parent:

- **The project**: `prepared.path`, the workspace.
- **The article**: the path `TASK.md` names, under `blueprint/roadmap/`.
- **The target**: `target_file` and `target_decl` from `prepared.record`.
- **The sources**: the article's `## Sources` links.
- **The claim**: your Choir lease on the task. Do not run `autoform claim`
  or take its `lake-build` claim; your `choir worker heartbeat` is the renewal
  it expects from its parent.

Tell it two things its own contract doesn't say:

- **Edit only the target file.** Do not update the article; the orchestrator
  records the proof after the merge.
- **Never touch a statement**, as `CONTRIBUTOR.md` § Boundaries says.

After a failed route, the specialists apply: `counterexample-hunter`,
`proof-strategy-researcher`, `mathlib-checker`, `prior-art-scout`.

The worker returns its changed paths, the commands it ran, the final build,
and `PROVED` or `FAILED`. That is the report § 3 asks for. On `PROVED`,
submit (§ 4). On `FAILED`, follow § When the mathematics is sound but the
task doesn't fit one PR, or release. A refutation from
`counterexample-hunter` is a "this statement is wrong" `choir-defect`.

Not used on a contributor's machine: AutoformBot's claims and its unattended
`autoform-worker` CLI. That CLI counts an attempt as a success only once the
article is edited.
