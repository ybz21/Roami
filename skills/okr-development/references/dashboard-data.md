# User HTML and dashboard data

Store dashboard/index.html, style.css and page.js under .roami/okr/.
Dashboard.json is the entry/binding authority. Existing schema1 widget rendering
works today; HTML entry/SDK loading is a proposed extension, not a current API.
Use existing ECharts for trends/bars, token-based number/progress cards and
semantic tables. Let the user choose their HTML/layout; React is not required.

The proposed read-only API is:

```js
const metric = await okr.data.read("github-stars");
render(metric);
const unsubscribe = okr.data.subscribe("github-stars", render);
```

A dataset contains snapshotId/revision, latest(value/unit), points(date/value),
source, asOf/capturedAt and quality/lastError. Null means unknown. A failed run
keeps the previous value and data version; its status can change independently.

The host reads the project-bound confirmed snapshot and passes only declared
bindings through this iframe's MessageChannel. HTML receives no database, server
path, credential, project switch, write API or arbitrary host capability. Sharing
one page-owned fetch/subscription prevents per-card polling. Hidden/closed views
release their subscription and reconcile the current version on return.

The Go file publisher writes dated observations and immutable snapshots, then
atomically switches state/current.json. Data/observations.jsonl is an export, not
a second import endpoint. Runtime SQLite owns schedules/jobs/runs/retries;
large source detail may remain in its source DB. Do not create dual metric masters.

Custom HTML must not execute inside the main app DOM. A production loader needs
confirmed assets, source-isolated iframe/handshake, a scoped read-only bridge,
resource policy, theme/locale and lifecycle handling. CSP is not a complete network
sandbox for arbitrary JS. Do not describe the prototype as that production loader.
