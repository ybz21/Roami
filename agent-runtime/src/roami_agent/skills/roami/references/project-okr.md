# Project OKR workspaces

For conversational creation of the whole directory, dashboard, Connector
bindings and team duties, read `skill://okr-development` first. Its bundle
reference describes the current configuration, including `dashboard` and `team`.

The real workspace is `#/projects/PROJECT_ID/okr` inside Roami. Discover the project's stable ID with the existing project tools. Discover this node's installed support with `roami project okr help`; old nodes may not have it. Use the normal authenticated CLI only where the active execution context permits bash and project writes. Do not read, copy or print saved credentials.

## From an objective to a proposal

Reason from the user's actual objective and available evidence. Propose outcome KRs, shorter experiments, and the metrics needed to distinguish progress from activity. Choose their number and meaning for this objective; do not impose a fixed list. Ask about the desired period, numerical targets and source accounts when they cannot be inferred. Get agreement on the measurement plan before connecting sources. Never invent a baseline or history.

In a creator project, completion rate and average watch duration diagnose quality alongside follower outcomes. In software maintenance, released latency and reliability remain separate from candidate benchmarks. In Roami promotion, GitHub star and fork outcomes remain separate from X clicks and Bilibili watch metrics. Content delivery and publication each need evidence.

## Read and write the same server workspace

```bash
roami project okr show PROJECT --json
roami project okr save PROJECT --file proposal.json --json
roami project okr record PROJECT --file observation.json --json
roami project okr collect PROJECT --file revision.json --json
roami project okr review PROJECT --file review.json --json
```

`--file -` reads one JSON object from stdin. File input is data, not shell code. Every write carries the currently observed `revision`. Creation uses 0. A conflict requires reading current state and reconsidering the change; never replay blindly. `save` changes configuration only; observations and reviews are server-owned append-only evidence.

Workspace configuration:

```json
{
  "revision": 0,
  "objective": "An agreed direction",
  "startDate": "2026-11-03",
  "endDate": "2026-12-29",
  "keyResults": [
    {"id":"growth","title":"An agreed outcome","horizon":"long","metricId":"followers","target":100,"mode":"increase","dueDate":"2026-12-29"}
  ],
  "metrics": [{"id":"followers","name":"Followers","unit":"people","source":"manual"}],
  "swarm": "",
  "autoCollect": false
}
```

`horizon` is `long` or `short`; `mode` is `increase`, `atLeast` or `atMost`. IDs remain stable across revisions, each KR references a defined metric, and due dates stay inside the agreed period. Values must be finite. Metric sources currently supported are manual observations and public GitHub. For GitHub use `source:"github",repo:"owner/repo",field:"stars"` or `"forks"`. `autoCollect` enables daily GitHub observation, not automatic content creation or publication. These sample numbers are schema examples, not user-approved targets.

For a manual observation submit `{"revision":N,"metricId":"followers","date":"YYYY-MM-DD","value":123,"note":"source and measurement window"}`. Observe the real account, identity, date and window first. Missing access means unknown; do not submit zero. A later correction is a new dated version. Never relabel an observation from another account or a simulated fixture.

`collect` takes `{"revision":N}` and reads confirmed GitHub bindings. The first verified snapshot establishes the real baseline; earlier history stays absent. The server isolates repository identities and retains same-day versions. Dates use Asia/Shanghai. Do not bypass a failure or rate limit by fabricating counts.

## Execute, reflect, execute

Associate the workspace with an existing managed Swarm's stable ID from `roami swarm ls --json` (`data[].id`). Create a Swarm or dispatch real tasks only when the user's request authorizes the work, following the session skill and native task routing. All members use the existing shared board and group chat; this workspace does not create a second message history.

An executor reports actual artifacts and acceptance evidence. A data role records verified observations. A separate reflection role reads the current workspace and delivery evidence, separates facts from hypotheses, then submits `{"revision":N,"summary":"evidence and uncertainty","actions":"specific next experiments"}`. The server records the evidence revision. Changed data or goals require a fresh review before adopting its conclusions.

The responsible coordinator turns an accepted review into concrete tasks on that same Swarm board, citing the review and KR. Do not call a task complete because a file exists, claim a post is live without a receipt, infer causation from two days of counts, or change another member's assignment. Publication follows the user's platform authorization. A recurring loop requires an actual configured scheduler; an idle persistent session alone does not prove daily execution.
