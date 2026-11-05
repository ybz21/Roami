# Connector Skill packages

The location is .roami/okr/connectors/<name>/SKILL.md. Python scripts live beside
it in scripts/; MCP/source contracts belong in references/. Connector.json only
binds confirmed source/account, metric IDs and workflow identity. It is not a new
arbitrary-command plugin entrypoint. One request/Skill may serve several metrics.

The current product only executes builtin GitHub and verified manual observations.
New package discovery, candidate batch publishing and general daily Skill jobs
are pending. Retain legacy schema1 definitions and their source/history on migration;
writing a new SKILL.md alone does not activate it. Keep preparation in a draft.

Python seed: parts/connectors/github/ contains a real public-data fetcher. Its
stdout is candidate evidence, never a confirmed observation or publish receipt.
It validates the repository and records the repository ID, date and capture time;
it does not backfill old dates or edit runtime/project data. Run in an authorized
managed workspace. Missing login or data remains unknown; do not use invented zero.

MCP seed: discover an available connection and its actual tool/effect/schema.
Record account and field mapping; a tool list is not collected data. Unknown effects
are not read-only by assumption. Respect existing authorization and no browser/phone
access unless that resource is authorized for the task.

The host must verify source identity, allowed metrics, units, date window, finite
values, Skill/code digest and current project revision before batch publishing.
Retry with the same run/batch identity, reconcile an unknown write first, and keep
the last valid snapshot on failure. Schedule definitions need a real durable runner,
time/timezone, nextDue and receipt; neither a reminder nor an idle agent suffices.
