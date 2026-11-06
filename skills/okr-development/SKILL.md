---
name: okr-development
description: Create or evolve an OKR project from conversation, including its file bundle, dashboard, connectors and persistent team roles.
---

# Develop an OKR

Turn the user's goal into a working project bundle, not a report about a possible
OKR. Use this workflow for creation and changes to an existing OKR. Ordinary team
chat or a progress question does not require rebuilding the bundle.

## Author from templates

The repository's `skills/okr-development/` is the canonical package. Runtime
wheels and native installers ship this same package, including templates. Read
only the resources needed for the requested change.

The complete initialization template is `assets/`, mirroring the project root.
It contains both AGENTS.md files, O/KR/method definitions, dashboard JSON and
HTML/CSS/JS, a Connector Skill, Main/team definitions, project workflows, memory,
empty data/evidence/state directories and a disabled schedule proposal. The daily-operations Skill provides a scoped external Main wakeup script
and kickoff/review prompts; its schedule remains disabled. Copy the
whole directory first, including hidden files:

```bash
okr_skill_dir=/path/to/skills/okr-development
okr_draft_dir="$(mktemp -d)"
cp -R "$okr_skill_dir/assets/." "$okr_draft_dir/"
```

Then combine `parts/` for Python/MCP sources, HTML fragments and executor roles.
Content-growth, product-delivery and operations under `examples/` are optional
reference overlays, not a substitute for the complete generic directory. Fill
intentional `{{...}}` template parameters from the user/project; targets, dates,
repo, role duties and widget count remain editable. Keep this work in the
isolated draft. Never put the package's fixtures or example counts into live
observations. Do not manufacture Main/member/provider IDs or current.json.

Produce the objective/KRs/methods, dashboard definition, user HTML/CSS/JS,
Connector Skill packages, desired team, instructions/memory locations and a
schedule proposal. Show the resulting runtime preview and meaningful diff.
Apply only supported definitions with the current project revision, then reread
the actual result. Check `projectFiles.htmlDashboardSupported` before enabling custom HTML.
Keep unsupported HTML or Skill-scheduler definitions as drafts; schema1 widgets
and builtin/manual sources remain available on older hosts.

A template choice does not replace long-lived members in an existing project.
Saving the desired team, registering it, dispatching work and activating a daily
schedule have separate receipts. Preserve the user's input on conflicts. Never
claim a template, script, HTML page or scheduled proposal has executed merely
because its files exist.

Read [the bundle contract](references/bundle.md) when preparing configuration.
For creation or a new layout, read [templates](references/templates.md) and choose
the complete `assets/` first, then combine the needed parts.
Read [the file-by-file authoring guide](references/authoring.md); edit existing
definitions in an isolated draft, preserving unrelated confirmed content.
For user-authored HTML or data that was collected but is absent from the board,
read [dashboard data](references/dashboard-data.md), including its change/publication
workflow. Align confirmed metrics, view references and accepted observations;
verify the actual rendered result.
For Python/MCP collection, read [Connector Skills](references/connectors.md).
For confirmed source/Skill bindings and candidate publication, read
[Connector batches](references/connector-batches.md).
The project directory is the workspace; `.roami/okr/` contains its definitions
and confirmed data. Keep existing directories, identities and history.

## Discuss and prepare

Read the bound project and current OKR before proposing changes. Reuse the user's
answers and existing authorization. Resolve only missing decisions that affect
the result: the objective and period, measurable outcomes, methods, data sources,
dashboard views, team duties and recurring collection needs. Choose their number for this goal; there is no
default number of KRs, charts or agents. Unknown baselines remain unknown.

Explain the proposed changes in the conversation. Show the goal and decisions,
not implementation identifiers. Preserve unrelated widgets, methods, roles and
source bindings. Creation of a definition does not authorize publication or
execution of all planned work.

## Create or update the bundle

For the project Main, discover `project_okr_context` and `project_okr_update`.
Read context, then use `operation: "save"` with the current revision and validated
configuration. The host fixes project identity. Do not supply another project or
use shell/SQLite to bypass these tools.

In an authorized Codex/Claude development terminal, use the installed
`roami project okr help` and the revision-checked `show`, `save` and `sync`
commands. `save` generates the bundle; do not manufacture confirmed snapshots or
observation history by writing scaffolding into a live project.

The configuration includes the dashboard and `team` definition. The server
publishes `dashboard.json`, `agents/team.json`, source-specific Connector files
and the remaining bundle together. Directly edited definitions remain drafts
until `sync` validates and confirms them. `save` is for a proposed configuration
before editing managed files and rejects pending file changes. Prefer saving
new metrics first to generate host compatibility files, then edit HTML and sync.
A conflict requires rereading; preserve incomplete drafts instead of clearing
confirmation state.

## Connect the team and data

For explicit desired-role bindings and interrupted saves, read
[durable team bindings](references/team-bindings.md). Use the host's capability
signal and exact registered member identities; preserve bindings when saving
other definitions.

Main is this OKR's persistent project conversation, separate from Home Main.
Reuse its bound Swarm. When the user requests a team, discover the current Swarm
and register the agreed roles through `swarm_members_register`; use its returned
member identities, not the role labels as task IDs. Reconcile existing roles
before adding any. If an existing executor/duty differs, resolve that change
explicitly rather than registering a replacement with a suffix. Saving
`agents/team.json` describes the desired team; it does not launch an agent or
prove that registration or execution succeeded.

Dispatch only requested work with `swarm_plan` and actual registered member IDs.
Continue later rounds with the original member/task and `task_steer`. Keep each
member's memory and original provider conversation. Unknown execution results
require reconciliation, not a new instance. Keep task results and group-chat
receipts distinct from independent acceptance.

Use the host-supported Connector batch workflow for confirmed Skills.
Collect unbound legacy sources through `collect`; record verified unbound manual facts
through `record`. Collection updates dated JSONL facts and a confirmed file
snapshot, which drives the dashboard. Source failures preserve existing facts;
they never become zero. Unsupported Connector execution or chart types require
a product change, not a claim that an arbitrary local script was loaded.

## Develop Connector Skills

Use a Skill as the entrypoint for each data-collection workflow. Keep each package under `.roami/okr/connectors/<name>/`, with `SKILL.md` at
its root. Keep Python fetching/normalization code in that Skill's `scripts/`; an MCP-backed Skill uses
available MCP tools and documents their account, inputs and output mapping.
Do not create a separate executable Connector plugin convention. Reuse one
Skill when several metrics share the same source and collection operation.
Read the Connector Skill and scheduling contract in
[the bundle contract](references/bundle.md#connector-skills-and-scheduling).

Separate the Skill, its confirmed source/metric bindings, and its daily schedule.
Ask for a missing collection time/timezone when enabling a schedule; a disabled
proposal can be prepared without it. Use a real scheduler receipt and next due
time to report activation. A reminder, an idle member, `autoCollect`, or a saved
schedule proposal does not prove that a custom Skill will run every day.

Check `projectFiles.connectorSkillBatches` and its live `connectorBatchProtocol`.
On capable hosts, confirm the Connector's files/source/metric bindings, have the
original member execute the reviewed Python/MCP workflow, and let Main publish
its reviewed evidence through the existing `record` batch operation. Check the
actual receipt and dashboard; a batch receipt is not task acceptance or a schedule.
Older hosts retain registered GitHub/manual compatibility operations. Daily Skill
execution still needs its real scheduler and nextDue receipt; a saved proposal or
builtin autoCollect is not that runner. Preserve the original Main and team.

## Operate and learn

The complete root `assets/AGENTS.md` specifies dashboard/data work, personal and
team memory, daily/weekly/monthly/yearly archives, project Skills and scoped
scheduling. Merge these durable sections into an existing project root AGENTS.md
without losing its own rules. Copy the matching manuals, including memory.md and
skills.md; links alone do not replace the root working agreement. Preserve real
identities, evidence and existing customizations.

For an existing team's daily execution, browser validation, recovery, memory and
scheduling, read [the daily loop](references/daily-loop.md). Use `roami chrome`
for the actual Main/group/member and dashboard interactions. Preserve the original
Main and member identities; distinguish human `swarm say` from Main `swarm_post`.
Never probe live write endpoints with placeholder content. Extract only verified
lessons, keeping project IDs/accounts and private transcripts out of this package.

## Verify the result

Reread the saved workspace and actual files. Check widget/metric bindings, source
identity, the confirmed revision and desired role definitions. Compare the
managed team's current roster and receipts with the plan. Report what was
created, what data was actually obtained, and any missing access or unsupported
view. Return the project entry and usable files. Do not say the team ran, a post
was published, or a dashboard is live merely because its definition was saved.
