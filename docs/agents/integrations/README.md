# Integrations — running another tool inside Choir's loop

Choir distributes the work; it does not insist on how the work is planned
or proved. The orchestrator playbook leaves the plan to you
(`ORCHESTRATOR.md` § Plan before you publish), and the contributor manual
leaves the proving to the worker (`CONTRIBUTOR.md` § 3. Prove it). A tool
that plans, orchestrates, or proves can fill either slot while Choir keeps
the rest: tasks, leases, workspaces, pull requests, the gate, and the merge.

When the user names such a tool — "use AutoformBot for orchestrating",
"use AutoformBot as a worker" — read its note here and run the loop with the
tool in the slots the note names. Every step the note does not mention runs
exactly as the playbook says.

| Tool | Note | Slots |
|---|---|---|
| AutoformBot | [`autoform-bot.md`](autoform-bot.md) | planning and statements (overseer), proving (contributor) |

A note answers the same questions for every tool:

- **Setup** — what the tool adds to the project repo, and what it must not
  run on pull requests.
- **The plan** — where it lives, how to read which nodes are ready, and how
  a node becomes a task.
- **Statements** — who writes them, and where. A worker never touches one
  (`CONTRIBUTOR.md` § Boundaries), whichever tool it runs.
- **Each pass** — the check that replaces `sync-graph`.
- **After a merge** — how the plan records it.
- **The worker** — what runs inside a claimed workspace, and which of the
  tool's own steps it skips there.

A tool with no note can still fill a slot: the playbook's rules bind it the
same way, and the note is where what you learn about it goes.
