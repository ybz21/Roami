# Copy the complete generic template first

Read [the file-by-file guide](authoring.md).
Copy `assets/.` to a new empty project draft. The assets directory itself is the
project root: AGENTS.md, README.md and .roami/okr/, including its own AGENTS.md. Combine only the
needed `parts/` next; business examples are optional overlays, not the entrypoint.


`examples/<id>/config.json` is a current schema1 configuration seed;
`template.json` explains decisions still required. The seeds do not include
observations, Main/member/provider identities or a running schedule.

- content-growth: public repository metrics and a small content team.
- product-delivery: manually verified milestones and critical workflows.
- operations: observed business metrics and investigation duties.

These are starting points, not fixed KR/role counts. On an existing project keep
unrelated widgets, source identities and actual members. Resolve an intended
change against the latest revision rather than applying a whole template blindly.

Fill `{{startDate}}`, `{{endDate}}`, `{{githubRepo}}` and agreed numeric targets
before validation. Do not turn missing baseline/access into zero. Config seeds
use supported widgets and source protocols; the user HTML and general Connector
Skill packages are preparation for the documented host extensions.

Start by copying `assets/.` into an empty draft, preserving .roami.
Read [the file-by-file guide](authoring.md), then use the reusable dashboard/ files for custom HTML. Replace metric binding
parameters with agreed IDs. The host injects `okr.data`; these files do not fetch
server paths or credentials and show a waiting state if the SDK is unavailable.
Select the Python or MCP package seed under `parts/connectors/`, put it in
`.roami/okr/connectors/<name>/`, then record its actual account/source and metric
mapping. Copy neither fixture observations nor sample execution receipts.

Keep schedule proposals disabled until supported host registration returns the
real schedule/nextDue receipt and the user has chosen time/timezone. Existing
`autoCollect` is only the builtin GitHub compatibility path, not this general runner.

After supported save/sync, reread the workspace and actual files. A draft tree
must not include a forged state/current.json or immutable confirmed snapshot.
