# Confirm a Connector Skill and publish its evidence batch

Read the current `project_okr_context`. The host must report
`projectFiles.connectorSkillBatches=true`; its `connectorBatchProtocol` describes
that host's actual schema. An older Python coordinator can use this through its
existing `project_okr_update` **record** operation when its Go host supports it.
This does not activate a newer builtin Skill catalog or bypass an upgrade gate.

## Confirm the workflow

Copy `assets/.` first, including both AGENTS.md files. The source/ Connector is a
proposal. Fill its source, account, timezone, window, metrics and actual Skill.
Combine Python/MCP parts as needed. Do not activate placeholders or copy example
facts. One Skill can serve several metrics from one source/window.

The optional `connectors` array in the OKR configuration contains:

```json
{
  "id": "source",
  "name": "Readable source name",
  "service": "mcp",
  "identity": "CONFIRMED_ACCOUNT_OR_SOURCE_ID",
  "timezone": "Asia/Shanghai",
  "window": "day",
  "files": ["SKILL.md", "references/source-binding.md"],
  "bindings": [{"metricId": "metric", "field": "CONFIRMED_FIELD"}]
}
```

Put declared files under `.roami/okr/connectors/<id>/`. Keep IDs distinct from
metric IDs and bind each metric once. `files` must include SKILL.md and all
reviewed workflow scripts/references (32 files, 1 MiB/file, 2 MiB total). No host
command or plugin entrypoint is installed. The host hashes declared bytes and
returns `packageSha256` on save/sync. Changing code remains pending until reviewed
confirmation. The digest does not prove execution or pin undeclared dynamic
imports, network services, or MCP implementation versions.

`github` uses the positive stable repository ID as `identity`, plus `repo`,
`snapshot`, `Asia/Shanghai` and existing github stars/forks metrics. Its canonical
source keys retain the existing GitHub history. Other services bind explicit
`manual` metrics; the measurement's source key then includes account/field/unit/
timezone/window, and its observations carry connectorId/batchId. These are real
Skill batches, not individual manual entry calls. Old unbound observations remain
in history and are not silently reassigned to a newly confirmed account.

Omitting connectors preserves current bindings; [] explicitly removes them.
Saving the configuration does not register a task, run the Skill, enable a daily
schedule, or replace Main/members. Existing builtin GitHub `autoCollect` is a
separate compatibility collector and is not silently disabled by binding a Skill.
Keep its receipts distinct; migrate daily execution only with a verified runner.

## Produce and review candidates

Main steers the **original** data member/task. The member reads the confirmed
Skill and uses authorized Python/MCP tools; it saves raw response bytes, source
identity, dates and current-run output. Main reads those files, checks actual
account/connection and measurement semantics, and performs the managed task's
independent acceptance. A declared account and SHA are integrity checks, not
cryptographic proof of remote truth. Generic/MCP values still need Main's semantic
review. GitHub additionally checks raw public repository JSON identity and counts.

For the GitHub part, run fetch_github.py with the confirmed repository ID. Export
the current workspace, then use `scripts/prepare_batch.py` with --workspace,
--candidate, --connector, --project, --evidence, --output and one persisted
--batch-id (32 lowercase hex). These output paths are project-relative, normally
inside this member's assigned dated topic directory; task/revision/run belong in the manifest metadata. The batch key
is caller-generated; never pretend it is a host task/run identity. The script
writes exact raw bytes and a request file; it publishes nothing. Existing differing
outputs stop instead of being overwritten. Never rerun preparation with another
key to recover an uncertain publication.

## Record through the bound Main

Use `project_okr_update(operation="record", payload=REQUEST_OBJECT)`:

```json
{
  "revision": 7,
  "batch": {
    "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "connectorId": "source",
    "packageSha256": "CONFIRMED_PACKAGE_SHA256",
    "sourceIdentity": "CONFIRMED_ACCOUNT_OR_SOURCE_ID",
    "date": "YYYY-MM-DD",
    "capturedAt": "RFC3339_WITH_OFFSET",
    "windowStart": "RFC3339_WITH_OFFSET",
    "windowEnd": "RFC3339_WITH_OFFSET",
    "values": [{"metricId": "metric", "unit": "CONFIRMED_UNIT", "value": 0}],
    "evidence": [{"path": "PROJECT_RELATIVE_RAW_FILE", "sha256": "RAW_SHA256"}]
  }
}
```

The zero above is a schema example, never a fact to copy. Missing values are
omitted; no observations means no publication. Units must match exactly. Snapshot
endpoints are equal; for GitHub they equal capturedAt. A day window starts at local
midnight and has an exclusive end after the start and no later than next midnight;
partial day observations are allowed and retain their real window. Dates stay
inside the confirmed project period and capturedAt cannot be in the future.

The host reads at most eight regular project-relative evidence files (4 MiB each,
8 MiB total), refuses symlinks/escapes, hashes and archives exact bytes under
state/connector-evidence/. Observations and connectorBatches receipts commit under
the same confirmed revision pointer. data/observations.jsonl and
data/connector-batches.jsonl are exported views; confirmed snapshots remain the
authority. Data-only publication retains the confirmed HTML bundle.

After an unknown result, read context and find connectorBatches by the same id.
A matching receipt is already committed, even if the current revision advanced.
When advertised, `roami swarm connector batch --input '{"swarmId":"...","batchId":"..."}'`
reads a compact receipt from the original Main's bound project. `confirmed` is a
historical fact; its receipt revision differs from the current workspace revision.
On older hosts, read the complete context artifact instead of its truncated preview.
Retry the exact original payload/revision/key if needed; do not refresh only its
revision or generate a new batch id. A reused key with changed content conflicts.
Preserve `note` too. `CONNECTOR_BATCH_ALREADY_CONFIRMED_REQUEST_CONFLICT` means
the old fact exists and this request conflicts; it does not discard the old batch.
`requestSha256` fingerprints the host's typed request, including its original
revision and batch. It is not the raw file SHA or an arbitrary sorted-JSON hash.
Check evidence file SHA against evidence bytes; do not invalidate a confirmed
receipt because a locally reserialized request has a different hash.
Source/code/evidence failures retain earlier facts. Reread a conflict and prepare
a new batch only after proving the old one was not published.

New publications expand a later collection's coverage. Collect that new set in a
fresh real batch; the earlier set remains valid at its earlier capture time.

Reopen the real dashboard with roami chrome and verify current-source values,
unknowns and same-day append order. A data receipt does not prove task acceptance,
public posting, or a daily schedule. Schedule/nextDue and platform receipts remain
separate. Never create a replacement Main or data member to bypass a failure.
