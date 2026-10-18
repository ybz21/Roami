---
name: roami-dispatch
description: Route user work through Roami CLI to an existing Codex or Claude session, a new background executor, or a new project. Use for project/session discovery, message delivery and execution follow-up.
---

# Roami dispatch

The user has one persistent Main conversation. Codex, Claude and native workers are background tasks, not additional user chats. Keep progress and results bound to the originating Main.

## Discover and act

- Named existing session: `target_search(kind="session", query=...)` or `target_resolve`; immediately `session_send(sessionId, text)` after identifying one exact destination. User instructions authorize that message; do not request confirmation again.
- Named project: find its stable projectId, then `target_search(kind="session", projectId=..., query=...)`. This is the complete paginated membership. Never infer membership or absence from a project's top-three card.
- Reuse the explicit existing session. If multiple suitable sessions remain and context cannot select one, `ask_user` with 2–4 recognizable options. Labels include project, session and executor where known; do not ask for internal IDs.
- New work in an existing project: `delegate(executor="codex"|"claude", target={kind:"project", projectId:...}, goal=...)`. The executor prepares its workspace in the background. Do not create another session when asked to continue a named one.
- Explicit new loose task: `delegate` with `kind:"new_session"` and an absolute directory discovered or supplied in context.
- Explicit new project: `delegate` with `kind:"new_project"`, name and optional absolute baseDir. Do not use new-project creation as a workaround for an existing session's missing lifecycle hooks.

## CLI contracts

The structured tools invoke argv-based CLI adapters, not an unrestricted Main shell:

| Tool | CLI |
| --- | --- |
| project discovery | `roami project ls --json` / `roami project show ID --json` |
| project session discovery | `roami project sessions ID --json` |
| live session discovery | `roami session ls --live --json` / `roami session resolve NAME --strict --json` |
| existing session message | `roami agent execution send-message --file -` |
| new background executor | `roami agent execution launch --file -` |
| new project provisioning | `roami project create` through the existing provision adapter |

Write payloads go over stdin with persisted idempotency keys. Main must not synthesize tmux send-keys or bypass CLI identity and workspace rules. Configured provider credentials are excluded from child CLI environments.

## Evidence and follow-up

- `session_send` state `delivered` proves prompt submission only. `executionTracked=false` means no lifecycle completion callback; do not call it completed or fabricate progress.
- `delegate` initially proves queue acceptance only. Use `task_status` and persisted executor reports for running/completed/failed state; the activity stream exposes actual tool and executor events.
- Failure stays failure; uncertain delivery stays unknown. Do not retry an unknown write or create a second session to work around uncertainty.
- Each action should be visible as a compact Main activity with its destination and real status. Ask real missing decisions using `ask_user`; do not replace options with a free-form confirmation request.
