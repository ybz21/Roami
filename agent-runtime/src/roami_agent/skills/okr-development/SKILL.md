---
name: okr-development
description: Create or evolve an OKR project from conversation, including its file bundle, dashboard, connectors and persistent team roles.
---

# Develop an OKR

Turn the user's goal into a working project bundle, not a report about a possible
OKR. Use this workflow for creation and changes to an existing OKR. Ordinary team
chat or a progress question does not require rebuilding the bundle.

Read [the bundle contract](references/bundle.md) when preparing the configuration.
The project directory is the workspace; `.roami/okr/` contains its definitions
and confirmed data. Keep existing directories, identities and history.

## Discuss and prepare

Read the bound project and current OKR before proposing changes. Reuse the user's
answers and existing authorization. Resolve only missing decisions that affect
the result: the objective and period, measurable outcomes, methods, data sources,
dashboard views and team duties. Choose their number for this goal; there is no
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
until `sync` validates and confirms them. A conflict requires rereading.

## Connect the team and data

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

Collect registered sources through `collect`; record observed manual facts
through `record`. Collection updates dated JSONL facts and a confirmed file
snapshot, which drives the dashboard. Source failures preserve existing facts;
they never become zero. Unsupported Connector execution or chart types require
a product change, not a claim that an arbitrary local script was loaded.

## Verify the result

Reread the saved workspace and actual files. Check widget/metric bindings, source
identity, the confirmed revision and desired role definitions. Compare the
managed team's current roster and receipts with the plan. Report what was
created, what data was actually obtained, and any missing access or unsupported
view. Return the project entry and usable files. Do not say the team ran, a post
was published, or a dashboard is live merely because its definition was saved.
