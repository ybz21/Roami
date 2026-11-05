# OKR bundle contract

## Files and authority

```text
PROJECT/
  AGENTS.md
  .roami/okr/
    okr.json                         objective, KRs, methods and metric definitions
    dashboard.json                   registered widgets, order and metric bindings
    connectors/METRIC_ID/
      connector.json                 source binding and execution type
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
  YYYY/YYYYMM/YYYYMMDD/               deliverables and acceptance evidence
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
`{revision:N,metricId,date,value,note}`. Same-day corrections append versions.
After a source change, old source identities remain in history and are not
relabeled as the new source. Preserve the last confirmed revision on failure or
concurrent edits. Do not edit Connector Go references and call them executable
plugins; custom HTTP/SQL/scripts need a registered Connector protocol first.
