# User HTML and dashboard data

Copy the complete `assets/.` first. Dashboard HTML/CSS/JS live at
`.roami/okr/dashboard/`; `dashboard.json` declares the entry, asset files,
metric IDs and optional host libraries. Check `projectFiles.htmlDashboardSupported`
on the current workspace before enabling schema2. Older hosts use schema1 widgets.
The reusable schema2 overlay is `parts/dashboard/html/dashboard.json`.

## Write the view

Use ordinary HTML/CSS/JS. React and a build step are not required. Cards/tables
use semantic HTML and host tokens; optional `libraries: ["echarts"]` provides the
installed ECharts build after `okr.ready()`, without a CDN. The complete template
supports number cards and the trend/bar fragment in `parts/dashboard/`.

```js
await okr.ready();
const draw = data => { element.textContent = data.latest.value ?? "Unknown"; };
draw(await okr.data.read("github-stars"));
const unsubscribe = okr.data.subscribe("github-stars", draw);
window.addEventListener("pagehide", unsubscribe);
```

`okr.data.ids` lists declared metric IDs. `read(id)` returns a fresh copy;
`subscribe(id, callback)` receives later snapshots and returns unsubscribe.
Only IDs declared in the confirmed manifest are readable. There is no database,
file-path, credential, write, project-switch or arbitrary host API. Use
`okr.context.locale/theme/size/pointer/revision` and injected design tokens.
Redraw charts when a subscription arrives; dispose charts/listeners on pagehide.
Use ResizeObserver for chart dimensions, and `data-size`/`data-pointer` for layout.

A dataset has id/name/unit, snapshotId/revision, latest(value/date/capturedAt),
points(date/value), source(kind/identity/resource), asOf, quality and lastError.
Null means unknown; observed zero stays zero. Same-day corrections use the latest
appended fact, and a changed source excludes old-source history. `quality` is
currently observed/unknown. `lastError: null` does **not** assert collector health:
the confirmed workspace does not yet expose per-collector failure/freshness state.
A failed collection preserves the last successful observation.

## Confirm assets and data

Declare UTF-8 .html/.css/.js assets under dashboard/ (up to 32 files, 1 MiB each,
2 MiB total), and include the entry. Relative script src and stylesheet href are
rewritten from these exact assets. Inline scripts/styles and data images work.
Remote resources, forms, embedded frames, refresh meta and project-relative paths
outside dashboard/ are rejected. Bundle module imports before publishing; bare
imports and a network module loader are unsupported. CSS imports/fonts are not
host-resolved. Use system fonts and the provided tokens.

Save/sync with the current project revision confirms the files and records an
immutable content digest. Edits stay pending until confirmed, even if observations
or reviews advance meanwhile. Invalid assets cannot replace the confirmed view.
The host serves only that digest and a project-bound readonly snapshot stream.
The page's existing shared refresh drives all cards; do not add per-card polling.
Switching projects/nodes, hiding/closing the page or leaving the tab closes the
channel and frame. Returning rereads the current confirmed configuration.

The Go publisher stores observations/reviews and immutable snapshots in the OKR
bundle and atomically switches state/current.json. Observations.jsonl is an
export, not a second import endpoint. The host project-okr.db stores confirmed OKR workspaces and operation receipts;
separate runtime storage owns schedules/jobs/runs. The project collection.sqlite3
is only a collection registry, not a dashboard data source;
never invent a schedule or mutate current.json to claim a Connector ran.

## Browser boundary

The host uses a sandboxed iframe with an opaque origin and a single MessageChannel.
It injects the SDK before user scripts and transfers only declared datasets,
locale/theme/tokens and requested host libraries. CSP denies fetch/socket, remote
scripts, frames/forms/workers; the document response also enforces sandboxing.
Do not describe this as a complete network/CPU sandbox for arbitrary JavaScript:
self-navigation remains possible. Use reviewed project-authored views. No secret
or host capability belongs in the data stream. A second frame load closes it.


## Change a view after collecting a new field

A successful source read may return a field the current dashboard never declared.
Read the confirmed context and actual dashboard assets first. Match the requested
field to its metric ID, unit, source/account/item and measurement window. Reuse an
existing matching metric; add the requested metric if absent. Do not repurpose an
unrelated metric (plays cannot stand in for completion percentage or watch time).
Observed zero and unavailable data have different meanings.

For JSON views update dashboard.widgets. For HTML views update the confirmed
metric definitions, dashboard.html.metricIds allowlist and the corresponding
HTML/JS rendering together. A static data-metric attribute is only a template
convention: page.js must read that same ID with okr.data.read and subscribe.
Preserve unrelated resources and widgets. Data belongs in accepted observations,
not hardcoded HTML, another private JSON file or a database fetched by the frame.

Use save for a proposed config before editing managed files. Once files have
changed, use revision-checked sync for the complete bundle; save rejects pending
changes. For new metrics, prefer save first to generate host compatibility files,
then edit the HTML and sync. Older unbound manual metrics require the exported
connector.json and unchanged store.go reference as well; these are compatibility
artifacts, not executable custom Connectors. Preserve incomplete drafts and use
the host's existing export structure, rather than deleting confirmation state.
Then independently review evidence and
publish through record using the host's actual protocol: a bound Connector Skill
uses its confirmed batch identity; an unbound manual metric uses the manual
observation operation. See [Connector batches](connector-batches.md). Re-read on
conflicts; never hand-edit current.json, dated exports or the runtime database.

Accept the change only after checking each link: confirmed metric -> declared
view reference -> accepted observation for the same metric/source -> dataset API
-> actual rendered value. Preserve prior history. Report the platform's as-of
time separately from when collection occurred, and name any values still unknown.
A saved raw file, Skill registration, sent request or agent message is not proof
that a value reached the dashboard. Main owns this final publication and check.

## Structured source rows

The complete template includes `assets/.roami/okr/skills/dashboard-storage/`:
a standard-library SQLite source store with declarative schemas, immutable row
versions, transactional/idempotent ingestion, scoped reads/exports and consistent
backups. Read its SKILL.md before initialization. It starts empty and does not
replace host confirmation, dataset publication or the read-only HTML SDK.
