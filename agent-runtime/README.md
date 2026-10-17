# Roami Agent runtime

Python owns conversations, model loops, delegation, memory, context and delivery semantics. Go remains the single public authentication boundary and owns the unified CLI and storage catalog. The service, CLI and main chat frontend are runnable; additional executor targets and proactive delivery policy are still being implemented. Nothing has been deployed to the running user instance.

## Development and verification

```sh
cd agent-runtime
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

Dependencies are pinned in `uv.lock`. Tests use temporary databases and injected model/HTTP transports; they never start a real coding Agent or use a live model account. The cross-language test builds the actual Go CLI, registers the Agent database, starts Python through that CLI, streams from a local HTTP model fixture, reads the durable answer, posts a proactive message and verifies maintenance-lock exclusion. The root quality gate runs these checks too. A separate integration test starts actual Go runners in an isolated tmux server with substitute `codex`/`claude` executables, verifying multiline input, literal shell characters, replay/conflict handling, cancellation, nonzero exits and interrupted-launch reconciliation.

## Run in an isolated instance

From the repository root:

```sh
go build -o /tmp/roami-agent ./cmd/roami
/tmp/roami-agent agent setup --runtime-dir "$PWD/agent-runtime"
scripts/dev/isolated-roami.sh /tmp/agent-demo /tmp/roami-agent agent init --runtime-dir "$PWD/agent-runtime"
cp agent-runtime/agent.example.toml /tmp/agent-demo/agent.toml
# Edit endpoint/name in agent.toml, and supply the selected key_env in the service environment.
scripts/dev/isolated-roami.sh /tmp/agent-demo /tmp/roami-agent agent serve --runtime-dir "$PWD/agent-runtime"
```

`[model].endpoint`, `name`, optional `worker`, and `key_env` select the provider, Main model, Worker model and credential environment variable. Keep credentials in a private file outside the checkout (directory mode 0700, file mode 0600), load that file into the launcher environment, and never place the key in TOML, command arguments, screenshots or version control. Configurations are instance-local; changing them requires restarting that instance's Python service. Verify both streaming and tool calls against the selected model: a model listed by `/models` may still be unavailable to the account.

In another terminal, use the same instance wrapper with `agent status`, `agent new --title NAME`, `agent send --conversation ID --text TEXT`, and `agent history --conversation ID`. Sending returns a durable intake receipt; it does not wait for model completion. `agent report --task ID --run ID --revision N --file result.json` is the local executor callback. `agent notify --conversation ID --source SOURCE --key KEY --file message.txt` is the trusted local trigger adapter. Use stable keys when retrying.

Public HTTP/SSE is `/api/agent/*` on the existing Go server, using its normal login. Python listens only on a private Unix socket (0600 under a 0700 directory); it does not implement a second login service. Go strips browser-supplied owner/cookie/auth headers and forwards the verified current single-user identity. Internal report/notify endpoints are not publicly mounted. For an installed binary, set `ROAMI_AGENT_RUNTIME` or pass `--runtime-dir` to locate the Python project.

## Implemented

- `frontend/src/components/agent/`: authenticated streaming Main chat, per-conversation drafts/history, retained desktop project/session tree and project quick task entry, coding target selection, task progress, source-backed memory editing, context summary/manual compression and six slash commands. In-app notifications stay unread until a completed message is visible and unobscured; opening the inbox alone does not consume them. Mobile keeps the existing four navigation entries. Browser tests cover message replay, stream framing/Unicode, stale conversation cancellation and visible read confirmation; physical Android acceptance remains pending.

The implementation follows the approved [code layers](../docs/design/20261017-agent框架设计/technical/index.html). `app.py` is the composition root and lifecycle entry; the former flat `runtime.py` and `main.py` modules have been removed.

| Layer | Implemented responsibility |
| --- | --- |
| `protocol/` | HTTP payloads, model events, tool contracts, errors and injected Loop ports |
| `server/` | Private HTTP/SSE routes and instance configuration; no business SQL in routes |
| `conversation/` | Idempotent intake, turn mailbox, message history, branches and interruption |
| `core/loop.py` | Main/Worker model loop over injected model/context/journal/catalog/manifest/budget/clock ports; no Web, CLI or SQLite implementation imports |
| `providers/` | Configurable streaming chat-completions adapter, fragmented tool arguments, usage and incomplete-stream errors |
| `context/` | Prompt projection, source/epoch snapshots, manual/automatic compression and paired tools |
| `memory/` | Source-validated candidates/confirmation, background extraction, timezone-aware daily aggregates, versions, tombstones and forgetting provenance |
| `retrieval/` | Validity/scope filtering before limits, literal OR CJK bigram FTS and bounded single-character fallback |
| `dispatch/` | Task intents, preparation, tree/budgets, scheduling, recovery, cancellation and verification |
| `executors/` | Native branch executor and Roami unified CLI coding adapter |
| `tools/` | Validated registry, short Main catalog, bounded Worker Shell/HTTP/Skills and lazy MCP connections |
| `replies/` | Proactive messages, delivery outbox and monotonic unread confirmation |
| `storage/` | Single SQLite writer, transcript/turn repositories, content-addressed artifacts, locks and transactional migrations |
| `observability/` | Persisted prompt manifests, model/catalog fingerprints and usage trace |
| `migrations/` | Versioned initial DDL and ordered upgrades, also included in installed wheels |
| `backend/agentproxy/` | Go authenticated public proxy with immediate SSE flushing |

`internal/agentruntime` keeps CLI/private transport and unified path/catalog registration. Python owns the Agent business DDL; Go does not write its business tables. Architecture tests enforce the core/contract/HTTP dependency boundaries. Existing lifecycle, restart, coding delegation, memory, compression and SSE tests exercise the refactored services.

The runtime schema started from the dated design's candidate schema, and additionally includes `conversation_reads`. Python owns the business DDL; Go registers the database and coordinates maintenance. Stop the runtime before unified database backup/layout migration. Current database backup does not yet form a complete Agent artifact recovery package.

## Memory lifecycle

Background extraction uses the Worker model with a separate injectable test port, a durable event cursor, bounded jobs and one low-priority memory slot. It never occupies a Main slot. Model output proposes candidates; owner/scope/hash validation happens again inside the write transaction. Candidates and conflicts remain outside recall until explicitly confirmed. Conflicts do not overwrite active records. Restart requeues interrupted extraction without changing its deduplication key.

The memory panel provides daily, task, conversation, project and preference views, source inspection and candidate review. Ordinary deletion removes a memory from recall and invalidates derived summaries. Complete forgetting additionally excludes traced transcript sources, memory tool blocks and dependent replies from future context while retaining visible history. Queued tasks with forgotten origins cannot dispatch; completion prompts redact their content. Input already delivered to an external model/process cannot be recalled. Older prompt manifests are reconstructed conservatively and can exclude additional dependent context.

Set `[memory].timezone` to an IANA name such as `Asia/Shanghai`; the default is UTC. Daily summaries coalesce by owner/date/timezone and archive after the local day ends. Explicit daily queries refresh current-day counts. Aggregation deduplicates user messages and task IDs, attributes projects separately from unassigned work, handles 23/25-hour days, and recomputes late historical events using an event watermark. Day summaries are not returned as ordinary knowledge unless a day is selected. Tombstones prevent background extraction or daily rebuilding from silently restoring deleted information.

## Coding execution transport

Main can discover targets on demand with `target_search` and `target_resolve`. These short read tools call the configured unified CLI and project API, without a Python project/session catalog or credential scheme. Searches return bounded pages of names and stable IDs, preserving duplicate names. Ordinary questions do not force a lookup. `roami session ls --live --json` reads one live identity snapshot without terminal capture, memory sampling or reconciliation; `roami session resolve ID --strict --json` rejects ambiguous labels and prioritizes exact identity. A failed observation is an error, never an empty catalog.

`roami agent execution launch --file SPEC.json` launches a one-shot coding process in a new, recorded tmux session. `status --key KEY` returns the durable result; `cancel --key KEY` requests cancellation and must be followed by status to confirm it. A spec contains `key`, `executor` (`codex` or `claude`), `prompt`, `timeoutSeconds` (1–86400), and either an absolute `directory` or a `projectId`. `model`/`permission` are optional; project specs additionally accept `base`/`remote`, or `workspaceId` to reuse a registered workspace.

The Go service uses the existing Agent registry, application session service, project store and worktree service. Arguments use argv, prompts use stdin, and private execution receipts live under `<DataRoot>/agents/executions`. It never guesses a Codex conversation ID. A reused key must have exactly the same spec; an unknown launch or interrupted runner is never blindly re-executed. Output remains visible in the session while running, with bounded stdout/stderr tails persisted for retrieval. Coding processes and shared Git workspace operations detach inherited repository bindings (including Git hook context) while retaining Git authentication settings. Timeout, cancellation and shutdown signals terminate the execution process group. The default permission comes from the coding CLI; explicit bypass is only applied when requested in the spec.

`executors/roami_cli.py` connects new loose-session and existing-project tasks to this transport. Set `runtime.coding_directory` explicitly, or provide an absolute `target.directory` for a `new_session` task. Go-launched Python defaults to the same Go executable for CLI calls. Launch returns without occupying a worker for the full coding duration; a separate monitor polls results and records the session binding. External executions have a separate bounded admission count and retain the original task deadline. Python restart observes the original launch; cancellation stays pending until the Go runner returns a terminal result. Missing launch evidence and observation failures are distinct, and uncertain execution is not replayed.

### Existing Codex TUI sessions

An explicit `kind=session, sessionId=ID` target continues an enrolled Codex TUI instead of launching a new process. The Go launcher requires a single pane, a known provider conversation ID and an observed idle lifecycle state. It journals the launch before using the existing paste-buffer/Enter helper, preserves the directory without fetch/reset and holds a durable workspace fence. Repeating an identical launch queries the receipt; uncertain submission is never sent again. Python records the exact provider conversation ID and returns the result to the original conversation. Completion still requires independent task acceptance.

`roami agent execution hook-config --executor codex` prints JSON composition data for the hook groups and `notify` argv. Merge the groups into trusted Codex hooks and the notifier into `config.toml`, preserving existing handlers; this output is not a drop-in TOML file. The command never modifies global configuration, trusts hooks or changes running user sessions. After enrollment, one observed ordinary prompt/completion establishes readiness. Sessions without a recorded complete lifecycle reject continuation before sending. Installation and refresh of this wiring in session creation remain pending.

Callbacks use `agent execution event --executor codex --file -` for hooks, and `--notification JSON` for Codex's notification argument. The implementation follows the official [hook contract](https://learn.chatgpt.com/docs/hooks) and [completion notification contract](https://learn.chatgpt.com/docs/config-file/config-advanced#notifications). `Stop` is deliberately insufficient because other hooks can continue the turn. Only `agent-turn-complete` with matching thread, turn and input hash can settle a launch. In-flight tools, subagent starts without definitive stop evidence, manual takeover or identity mismatches preserve uncertainty. Cancellation denies subsequent supported local tool calls and waits for completion evidence; it never destroys the reused session or treats a cancellation request as proof of stopping. Hook coverage is not a complete enforcement boundary.

Stop confirmation also checks the original pane process identity and dedicated `tmux-spawn-*.scope` cgroup, including reparented background processes. New task processes prevent settlement even when their original shell exited. This requires Linux procfs and a readable dedicated pane cgroup; unsupported hosts fail before submission. Processes already running outside the pane are distinguished by their original ancestry. This is observation of managed work, not an OS sandbox: processes moved outside the scope, remote effects and manual external writes still need reconciliation. Claude TUI continuation remains unavailable because its `Stop` hook alone does not establish final turn completion; one-shot Claude execution continues to work.

Tests use actual Go CLI subprocesses and Python persistence with isolated session fixtures, including duplicate submissions/notifications, mismatched identities, in-flight tools, background/orphan processes, cancellation and delivery to the original conversation. They do not contact a coding provider or message user sessions.

An external task whose deadline passes without a known terminal receipt requests cancellation and becomes `interrupted`, with an explicitly unknown attempt outcome. This releases its scheduler slot; Go's independent resource fence remains in force. The original conversation receives one durable interruption report. Polling continues to reconcile late terminal evidence into that attempt's history without promoting the interrupted task to success or replaying its launch. A known result that wins the database race cannot be replaced by a stale timeout observation. Cancellation of an uncertain reused session records the request while preserving unknown state; it does not claim the TUI stopped.

A `project` target uses `projectId`, with optional `base`/`remote`. Go resolves the stable ID (including aliases) through the existing project store, then uses the shared worktree service. Git projects require a successful fetch and create a new checkout from the returned fixed remote OID; local main stays untouched. Directory projects retain their project identity and execute in their existing directory. A caller cannot override a project's directory or silently substitute the loose-session directory. Preparation is journaled under the launch key, bounded to 120 seconds and charged against the same task deadline; retries return the same workspace receipt. Preparation failure saves a failed result and never starts the coding process. Workspaces are preserved on execution failure for inspection.

Go preparation returns a stable opaque `workspaceId` and persists its project/directory/branch/base/start-OID receipt under the instance data root. Passing `projectId` plus that `workspaceId` resumes the recorded checkout, validates its project and current worktree membership, and preserves local commits and uncommitted changes. Reuse rejects `directory`, `base` and `remote` overrides, unknown IDs, cross-project IDs, missing/moved paths and branch mismatches. It performs no fetch, checkout, reset or rebase; offline continuation is supported. Older receipts without workspace IDs need a new explicit preparation before this reuse path is available.

Managed coding runners take an exclusive writer lock for the canonical Git checkout (or the exact canonical directory outside Git). Symlink aliases and nested directories of the same checkout share the lock; separate linked worktrees do not. The durable writer receipt remains after a runner exits: a later writer requires the earlier run's terminal result, so a lost Go runner cannot release a potentially still-active child merely by losing its OS lock. Busy or uncertain workspaces fail before starting the coding process. This coordination covers framework-managed coding runs; coordination of external/manual workspace changes and non-Shell remote resources remains required.

Python exposes `preparing` until an actual running receipt arrives, persists the resolved target and workspace event, and inherits parent task deadlines. Existing-session continuation and external checkpoint Fork remain required. These targets fail explicitly; callers must not substitute an arbitrary current directory for a project target. External success still enters the verification path; this transport does not equate an exit code with meeting the user's goal.

## New project targets

A `new_project` target supplies `name` and an optional absolute `baseDir`. Native and coding executors first call the existing authenticated `roami project create` CLI, using a stable `--provision-key` derived from the run. Go's project API remains the catalog writer; Python never writes project metadata. The default parent is `<DataRoot>/projects`. The normal create command still supports adopting existing directories; Agent provisioning uses an exclusive path that rejects name/directory conflicts and placement inside another Git worktree.

Go saves intent before directory creation, verifies ownership before recovery/registration, checks catalog persistence and saves a durable resource receipt. Replaying the same request returns the same project ID, while changed parameters or a removed target fail explicitly. An ambiguous directory is preserved for reconciliation. Current Agent provisioning creates an empty directory project; configured templates/clone provisioning are still required. CLI login and the existing Go server connection must already be available; no additional Python login or fallback metadata writer is introduced.

After provisioning, execution uses the normal project workspace preparation and records the resolved project/workspace binding. Memory extraction and daily counts use the resolved project, with daily attribution bounded by the preparation event watermark. A directory project that is later initialized as its own Git repository keeps its workspace ID when continued; the registry refreshes checkout metadata without fetching or resetting it.

## Native Worker workspaces

A native project task uses the same Go workspace preparation and registry as a coding CLI task. Python requests `roami agent execution hold --file -` with a bounded JSON frame and keeps that process open for the task lifetime. Go returns the prepared workspace, holds the shared writer lock, and requires a second explicit `stopped` confirmation before saving a release result. EOF, owner death, a missing acknowledgement, or an unknown write leaves the workspace quarantined. This internal lease protocol does not report task success or satisfy task acceptance.

The native branch receives the trusted workspace in its system context and tool binding. Shell defaults to that directory; relative cwd resolves beneath it, and a task cannot substitute another configured root. Shell removes inherited Git repository bindings while preserving Git authentication settings. This is cwd validation, not an OS filesystem sandbox. Unbound analytical Workers can answer without a workspace; local Shell calls require preparation. Loose native tasks can use an explicit directory or `runtime.coding_directory` as their default.

Preparation consumes the task's original deadline. `preparing` becomes `running` only after the Go receipt and database binding are recorded. Cancellation or source forgetting during preparation prevents Worker admission. Local Shell cleanup stops its process group before cancellation is confirmed; cancelled remote/MCP writes with unknown outcomes cannot release the workspace and leave the task interrupted with an unknown attempt. Preparation failures also close the prepared native turn. Restart preserves uncertain ownership rather than automatically repeating work.

Cross-language tests use the real Go CLI, Python runtime and local Shell processes in an isolated registered project. They verify default cwd, task state ordering, independent acceptance, cancellation/child stop, workspace reuse, and quarantine after an uncertain cancellation. The provider is an injected fixture; these tests do not contact a real model or a user's coding sessions.

## Remaining work toward the full framework

1. Physical Android acceptance of the integrated chat, keyboard, touch navigation and safe areas; additional executor target controls and system push UI.
2. Finish automatic lifecycle wiring for existing Codex sessions and a definitive completion adapter for Claude TUI continuation. Broaden resource recovery for unknown preparation outcomes; never blindly retry an ambiguous launch.
3. Browser/Computer tool adapters, resource leases and artifact storage/backup, including binary MCP results. MCP stdio and Streamable HTTP adapters are implemented; unsupported binary/oversized results stop the call rather than entering model context.
4. Broaden legacy forgetting/re-learning recovery cases; implement provider cache controls and provider/model routing resilience.
5. Proactive triggers/scheduling, notification preferences, quiet hours, rate limits and existing App push delivery adapters. The notification store is implemented, but an outbox row is not proof of external delivery.
6. Broader end-to-end recovery, verification edge cases and real-device acceptance. A single real-provider memory extraction smoke check produced a source-backed candidate without activating it; no latency/cache/cost benchmark has run.

The design and product prototype remain in `docs/design/20261017-agent框架设计/`.

## Provider reference

The streaming adapter follows the official [chat-completions event reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events). It implements this explicit wire contract rather than assuming all provider APIs or models have identical tool/caching capabilities.

`model.max_retries` defaults to two retries and accepts 0–3. Only transient HTTP/transport failures before any normalized event is emitted can retry; partial visible text is never replayed. Backoff respects `Retry-After` and the original request deadline; cancellation interrupts the wait. Permanent/authentication errors, malformed events and redirects do not retry. The endpoint parser rejects embedded credentials, query/fragment values and non-loopback plain HTTP. Redirects are disabled even with an injected HTTP client. Provider diagnostics remain outside model context. See the official [error/recovery reference](https://developers.openai.com/api/docs/guides/error-codes).

`model.capabilities` declares a version and supported tools, streamed usage and cache parameters. Defaults preserve the existing text/function-call wire contract. Cache request parameters are opt-in: the deployment must verify the selected endpoint and both configured models, then declare support before enabling `model.cache`. A stable hashed key varies with route, model settings, namespace, first system message and tools; appending conversation messages preserves it. `mode=explicit` marks only the leading system/developer prefix through content-block breakpoints and leaves the stored context unchanged. It requires a system prefix. `mode=implicit` sends the configured cache options without adding breakpoints. The provider owns actual matching, retention and KV state; local fingerprints do not prove a hit or copy a Fork's KV cache. These optional fields follow the official [request contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

Prompt manifests now partition fingerprints by endpoint ID, model, serializer and capability/cache settings. They record hashes instead of endpoint credentials or full prompts. Usage retains provider counts and normalizes known input/output/cache-read fields; absent fields remain null, including unsupported cache-write counts. A successful retried attempt does not establish total cost across earlier attempts, so `retryUsageKnown` stays false. Separate endpoints/model versions do not reuse the same application fingerprint. Provider/model routing across different endpoints and performance/cost benchmarks remain pending.

## MCP connections

Configure named servers under `[tools.mcp.<name>]` as shown in `agent.example.toml`. A Worker calls `mcp_discover` for the relevant server; Main never waits for MCP startup or carries the full remote catalog. Each connection owns its SDK session in one actor and serializes its calls. Tools use namespaced, schema/version-bound aliases; catalogs are sorted for a stable model prefix. Directory changes remove old tools, and discovery/call refreshes refuse stale aliases before execution. Failed connections back off and reconnect on demand without replaying calls.

Stdio children receive the SDK's minimal default environment plus explicitly mapped `env_env` variables. HTTP credentials come from `key_env` or `header_env`; endpoint URLs cannot carry credentials. Raw server errors/stderr and progress messages do not enter ordinary logs or model context. Numeric progress events are bounded and persisted against the active turn lease. Calls have bounded queues, deadlines and output; cancellation sends a best-effort MCP cancellation notification and closes the connection. A remote cancellation is not proof that a write stopped: ambiguous outcomes are persisted as unknown, end the current turn and never automatically replay. Only explicitly configured `read_only` tools count as reads; server hints alone do not remove verification.

The adapter uses the official [Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0) for the [MCP transports and lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). Automated checks use real stdio processes and an authenticated local Streamable HTTP server, plus native Worker discovery/calls, catalog fingerprints, schema changes, timeouts, cancellation and unknown outcomes. They do not contact configured production MCP services.

## Artifact storage

The runtime upgrades schema v1 to v2 transactionally, preserving existing rows. Unsupported future versions fail without rebuilding the database; Go backup validation accepts both supported versions. Artifact bytes live under `<DataRoot>/agent-artifacts/blobs`, addressed by SHA-256, while SQLite stores separate opaque, owner-scoped references. Task/message attachment validates ownership and branch provenance. Writes are atomic and durable before publishing a reference; reads verify size and digest. A cancelled caller cannot release the runtime maintenance lock while filesystem work is still pending.

The authenticated Go proxy exposes `GET /api/agent/artifacts`, `GET /api/agent/artifacts/{id}`, `GET /api/agent/artifacts/{id}/content` and `DELETE /api/agent/artifacts/{id}`. Downloads use attachment disposition, disable caching and sniffing, and never expose storage paths. `[artifacts].max_bytes` defaults to 64 MiB. Deletion tombstones the reference without resurrecting it on a later upload; physical garbage collection and a complete file-inclusive backup package remain pending. Tool producer integration is the next step; these endpoints do not accept arbitrary file paths or public uploads.
