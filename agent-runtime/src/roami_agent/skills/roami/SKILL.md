---
name: roami
description: Use Roami projects, sessions, background tasks, executors, reminders, memory and node operations through the roami CLI.
---

# Roami

Use the `roami` CLI family. Discover unfamiliar commands with `tool_list(kind="cli",query="roami")` or run `roami help` in native bash. The returned command list carries each input schema and effect. Internal operation names are not separate CLI products. Browser work belongs to `skill://browser_use` and `roami chrome`.

Read only the relevant reference through `read`:

| Task | Reference |
| --- | --- |
| Projects, sessions and dispatch | `skill://roami/references/projects-sessions.md` |
| Task progress, reports, reminders and takeover | `skill://roami/references/agent-tasks.md` |
| Memory, files and external capabilities | `skill://roami/references/capabilities.md` |
| Login, node diagnostics, plugins and database | `skill://roami/references/node-operations.md` |

Native tasks pass a command string to bash, such as `{"command":"roami help"}`. Built-in task and session tools can be called directly; discovered CLI commands remain available. The host binds owner, conversation, task and request identity; never invent them or copy historical IDs. Professional terminals can also use normal flags shown by the node's CLI help. Known valid commands need no rediscovery. A listed command does not expand role permissions.

Use exact target identities and complete pagination. The user's request to send to an existing session authorizes delivery; ambiguity requires a concrete choice. Delivered/queued means accepted, not verified completion. Unknown writes require reconciliation before retry.

New work uses `delegate` with `goal`; optionally choose `executor`, `directory`, `projectId` or `sessionId`. The host supplies routing, provenance and execution bookkeeping. Continue tracked work with `task_steer` using `taskId` and `text`; the host reads its current revision and preserves its executor/workspace. Handle every independent part of the user's request, then finish without polling accepted work. Completion arrives automatically. Use `task_status` for an explicit progress or results request. Do not confuse task IDs with tmux session IDs.

The user has one Main; background results return there. Keep required stage confirmations. Native bounded work and professional complex work follow the current host routing policy; no extra approval is implied by this Skill. Built-in capabilities stay read-only; external entries keep their configured enable/disable policy.
