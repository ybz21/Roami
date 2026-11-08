# OKR bundle contract

## Files and authority

```text
PROJECT/
  AGENTS.md
  .roami/okr/
    okr.json                         objective, KRs, methods and metric definitions
    dashboard.json                   registered widgets or confirmed HTML entry/bindings
    dashboard/index.html             user-authored display (check host HTML capability)
    connectors/NAME/
      SKILL.md                       collection workflow (new package protocol)
      connector.json                 source/metric binding
      scripts/                       Python when needed
      references/                    MCP/source details when needed
    agents/
      main.json                      coordinator instructions and project skills
      main.md
      team.json                      desired persistent roles, not live instances
      swarm.json                     bound managed team identity
    skills/                          project-specific workflows
    memory/
      team.md                        shared facts and working rules
      decisions.md                   important decisions and unresolved matters
      members/MEMBER_ID/memory.md     each persistent member's notes
    data/observations.jsonl           dated observation versions
    data/reviews.jsonl
    evidence/                        original review evidence
    state/current.json               atomic confirmed-version pointer
    state/confirmed-revisions/       immutable confirmed snapshots
  materials/YYYY-MM-DD/             readable topic deliverables and acceptance evidence
```

`save` creates the core bundle. Member notes and dated deliverables are created
when used, not fabricated during setup. Existing instructions and history are
preserved. SQLite remains the legacy archive and ownership index for OKR files;
live task/conversation identities remain owned by the managed runtime.

The UI reads the confirmed snapshot via the project API. `okr.json`,
`dashboard.json`, `agents/team.json` and Connector definitions are editable inputs
to `sync`. JSONL files are exported facts, not a second import endpoint: do not
replace their contents to change live data. The collector publishes both the
facts and the new snapshot before advancing `state/current.json`.

## Configuration submitted to save

Use only these fields, retaining existing optional definitions:

- `revision`: observed current revision; 0 for a new OKR.
- `objective`, `startDate`, `endDate`: agreed objective and YYYY-MM-DD period.
- `keyResults`: `{id,title,horizon,metricId,target,mode,dueDate}`. `horizon` is
  `long` or `short`; `mode` is `increase`, `atLeast` or `atMost`.
- `metrics`: `{id,name,unit,source}`. `source` is `manual` or `github`; GitHub
  additionally requires `repo: "owner/repo"` and `field: "stars"` or `"forks"`.
- `initiatives`: `{id,title,channel,keyResultIds,description,acceptance}`.
- `dashboard`: `{schemaVersion:1,widgets:[{id,type,title?,metricIds?,keyResultIds?}]}`.
  Supported types are `keyResults`, `metricTrend`, `nextAction`; the data page
  displays result and trend widgets. Each selected metric has its own trend card.
  Widget IDs are stable; referenced KR and metric IDs must exist.
  On hosts with `projectFiles.htmlDashboardSupported`, schema2 uses
  `{schemaVersion:2,widgets:[],html:{entry,assets,metricIds,libraries?}}`;
  see [dashboard data](dashboard-data.md) for file and SDK contracts.
- `team`: `{schemaVersion:1,roles:[{id,name,executor,duty}]}`. Choose duties from
  the goal; an empty roles list is valid for Main-only work. IDs and names are
  unique. Executors are `native`, `codex`, `claude`, `opencode`, `pi`; actual node
  availability is checked by the managed team, not by the file definition.
- `swarm`: bound team's actual ID, or empty if no team has been requested.
- `autoCollect`: whether daily registered GitHub collection is enabled. This
  does not schedule arbitrary member work or external publication.

IDs are stable identifiers, not generated instance names. Do not submit derived
`sourceKey`, project/conversation IDs, observations, reviews or timestamps as
configuration. A role's local definition ID is not a managed member ID. Use
current registration receipts to connect roles to real members; conflicting or
ambiguous legacy roles require explicit reconciliation, never a name guess.

## Connector and data flow

GitHub definitions generate a builtin Connector with repository and field.
The registered collector reads the public repository API and records the stable
repository identity plus field. Manual sources record verified account, date,
measurement window and evidence; missing login is unknown, not zero.

`collect` accepts `{revision:N}`. `record` accepts
`{revision:N,metricId,date,value,note}` for an unbound explicit metric. On a host
with `connectorSkillBatches`, it also accepts `{revision:N,batch:{...}}` for a
confirmed Skill workflow; see [Connector batches](connector-batches.md).
Same-day corrections append versions.
After a source change, old source identities remain in history and are not
relabeled as the new source. Preserve the last confirmed revision on failure or
concurrent edits. Do not edit Connector Go references and call them executable
plugins. Custom Python/MCP execution follows the Skill contract below; it is not
an executable Go-reference or JSON command plugin protocol.


## Connector Skills and scheduling

A Connector is a data-collection **Skill**. `SKILL.md` is its workflow entrypoint;
Python and MCP are implementation choices within it. Keep a source shared by
several metrics in one Skill when collection is naturally atomic. A typical
project-owned Skill uses this structure:

```text
connectors/collect-SOURCE/
  SKILL.md                 source/account, metric scope, collection and validation
  scripts/                 Python code when deterministic fetching is useful
  references/              MCP tools or source contracts when needed
```

Do not create empty script/reference directories for an MCP-only or simple Skill.
Source binding JSON describes the configured source; it is not another plugin
entrypoint. Keep secrets in the existing credential system, outside the bundle.
The Connector package location is `connectors/<name>/`, not project `skills/`.
A capable host confirms configuration.connectors and exposes those exact
Connector Skills in projectFiles.skills alongside registered project skills.
Check connectorSkillBatches and the live connectorBatchProtocol before using it.
Older hosts retain the proposal without activation. A confirmed definition is not
an execution receipt. See [Connector Skills](connectors.md).

Before enabling a collection Skill, establish the source/account, permission,
metric IDs, date window, unit and evidence required for each output. Python
scripts fetch and normalize; MCP Skills invoke actual available tools. Fetching
an MCP tool list is not collection. Neither path may invent missing values,
write runtime SQLite, replace confirmed snapshots, or bypass project revision
checks. Main submits validated facts through the registered project operation.

A daily schedule refers to the confirmed Skill and project, with a local time,
IANA timezone, enabled state and next due time. The scheduler owns execution
identity, deduplication and retry records in its database; the project files own
the Skill/source definitions and confirmed dashboard data. A scheduled run must
retain the Skill version, source binding, metric date, real evidence and publish
receipt. Recheck definition revision before publishing; concurrent changes need
reconciliation. Failed collection keeps the previous valid snapshot and reports
unknown/stale data; it does not write zero or claim success. Unknown publishing
outcomes require rereading the same run before retrying.

Current capability boundary: `autoCollect` schedules only the existing builtin
GitHub adapter. General daily execution of a Python/MCP-backed Skill is pending;
a reminder only sends a notification. Do not activate a second overlapping
collector or claim a custom schedule exists from either setting. When that
scheduler is implemented, use its persisted receipt rather than shell cron,
model-generated dates or keeping an agent alive as a timer.
