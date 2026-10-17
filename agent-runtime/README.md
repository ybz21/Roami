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
| `storage/` | Single SQLite writer, transcript/turn repositories, locks and migration loading |
| `observability/` | Persisted prompt manifests, model/catalog fingerprints and usage trace |
| `migrations/0001_initial.sql` | Versioned initial DDL, also included in installed wheels |
| `backend/agentproxy/` | Go authenticated public proxy with immediate SSE flushing |

`internal/agentruntime` keeps CLI/private transport and unified path/catalog registration. Python owns the Agent business DDL; Go does not write its business tables. Architecture tests enforce the core/contract/HTTP dependency boundaries. Existing lifecycle, restart, coding delegation, memory, compression and SSE tests exercise the refactored services.

The runtime schema started from the dated design's candidate schema, and additionally includes `conversation_reads`. Python owns the business DDL; Go registers the database and coordinates maintenance. Stop the runtime before unified database backup/layout migration. Current database backup does not yet form a complete Agent artifact recovery package.

## Memory lifecycle

Background extraction uses the Worker model with a separate injectable test port, a durable event cursor, bounded jobs and one low-priority memory slot. It never occupies a Main slot. Model output proposes candidates; owner/scope/hash validation happens again inside the write transaction. Candidates and conflicts remain outside recall until explicitly confirmed. Conflicts do not overwrite active records. Restart requeues interrupted extraction without changing its deduplication key.

The memory panel provides daily, task, conversation, project and preference views, source inspection and candidate review. Ordinary deletion removes a memory from recall and invalidates derived summaries. Complete forgetting additionally excludes traced transcript sources, memory tool blocks and dependent replies from future context while retaining visible history. Queued tasks with forgotten origins cannot dispatch; completion prompts redact their content. Input already delivered to an external model/process cannot be recalled. Older prompt manifests are reconstructed conservatively and can exclude additional dependent context.

Set `[memory].timezone` to an IANA name such as `Asia/Shanghai`; the default is UTC. Daily summaries coalesce by owner/date/timezone and archive after the local day ends. Explicit daily queries refresh current-day counts. Aggregation deduplicates user messages and task IDs, attributes projects separately from unassigned work, handles 23/25-hour days, and recomputes late historical events using an event watermark. Day summaries are not returned as ordinary knowledge unless a day is selected. Tombstones prevent background extraction or daily rebuilding from silently restoring deleted information.

## Coding execution transport

`roami agent execution launch --file SPEC.json` launches a one-shot coding process in a new, recorded tmux session. `status --key KEY` returns the durable result; `cancel --key KEY` requests cancellation and must be followed by status to confirm it. A spec contains `key`, `executor` (`codex` or `claude`), `prompt`, `timeoutSeconds` (1–86400), and either an absolute `directory` or a `projectId`. `model`/`permission` are optional; project specs additionally accept `base`/`remote`, or `workspaceId` to reuse a registered workspace.

The Go service uses the existing Agent registry, application session service, project store and worktree service. Arguments use argv, prompts use stdin, and private execution receipts live under `<DataRoot>/agents/executions`. It never guesses a Codex conversation ID. A reused key must have exactly the same spec; an unknown launch or interrupted runner is never blindly re-executed. Output remains visible in the session while running, with bounded stdout/stderr tails persisted for retrieval. Coding processes and shared Git workspace operations detach inherited repository bindings (including Git hook context) while retaining Git authentication settings. Timeout, cancellation and shutdown signals terminate the execution process group. The default permission comes from the coding CLI; explicit bypass is only applied when requested in the spec.

`executors/roami_cli.py` connects new loose-session and existing-project tasks to this transport. Set `runtime.coding_directory` explicitly, or provide an absolute `target.directory` for a `new_session` task. Go-launched Python defaults to the same Go executable for CLI calls. Launch returns without occupying a worker for the full coding duration; a separate monitor polls results and records the session binding. External executions have a separate bounded admission count and retain the original task deadline. Python restart observes the original launch; cancellation stays pending until the Go runner returns a terminal result. Missing launch evidence and observation failures are distinct, and uncertain execution is not replayed.

A `project` target uses `projectId`, with optional `base`/`remote`. Go resolves the stable ID (including aliases) through the existing project store, then uses the shared worktree service. Git projects require a successful fetch and create a new checkout from the returned fixed remote OID; local main stays untouched. Directory projects retain their project identity and execute in their existing directory. A caller cannot override a project's directory or silently substitute the loose-session directory. Preparation is journaled under the launch key, bounded to 120 seconds and charged against the same task deadline; retries return the same workspace receipt. Preparation failure saves a failed result and never starts the coding process. Workspaces are preserved on execution failure for inspection.

Go preparation returns a stable opaque `workspaceId` and persists its project/directory/branch/base/start-OID receipt under the instance data root. Passing `projectId` plus that `workspaceId` resumes the recorded checkout, validates its project and current worktree membership, and preserves local commits and uncommitted changes. Reuse rejects `directory`, `base` and `remote` overrides, unknown IDs, cross-project IDs, missing/moved paths and branch mismatches. It performs no fetch, checkout, reset or rebase; offline continuation is supported. Older receipts without workspace IDs need a new explicit preparation before this reuse path is available.

Managed coding runners take an exclusive writer lock for the canonical Git checkout (or the exact canonical directory outside Git). Symlink aliases and nested directories of the same checkout share the lock; separate linked worktrees do not. The durable writer receipt remains after a runner exits: a later writer requires the earlier run's terminal result, so a lost Go runner cannot release a potentially still-active child merely by losing its OS lock. Busy or uncertain workspaces fail before starting the coding process. This coordination covers framework-managed coding runs; coordination of external/manual workspace changes and non-Shell remote resources remains required.

Python exposes `preparing` until an actual running receipt arrives, persists the resolved target and workspace event, and inherits parent task deadlines. Existing-session continuation, new-project creation and external checkpoint Fork remain required. These targets fail explicitly; callers must not substitute an arbitrary current directory for a project target. External success still enters the verification path; this transport does not equate an exit code with meeting the user's goal.

## Native Worker workspaces

A native project task uses the same Go workspace preparation and registry as a coding CLI task. Python requests `roami agent execution hold --file -` with a bounded JSON frame and keeps that process open for the task lifetime. Go returns the prepared workspace, holds the shared writer lock, and requires a second explicit `stopped` confirmation before saving a release result. EOF, owner death, a missing acknowledgement, or an unknown write leaves the workspace quarantined. This internal lease protocol does not report task success or satisfy task acceptance.

The native branch receives the trusted workspace in its system context and tool binding. Shell defaults to that directory; relative cwd resolves beneath it, and a task cannot substitute another configured root. Shell removes inherited Git repository bindings while preserving Git authentication settings. This is cwd validation, not an OS filesystem sandbox. Unbound analytical Workers can answer without a workspace; local Shell calls require preparation. Loose native tasks can use an explicit directory or `runtime.coding_directory` as their default.

Preparation consumes the task's original deadline. `preparing` becomes `running` only after the Go receipt and database binding are recorded. Cancellation or source forgetting during preparation prevents Worker admission. Local Shell cleanup stops its process group before cancellation is confirmed; cancelled remote/MCP writes with unknown outcomes cannot release the workspace and leave the task interrupted with an unknown attempt. Preparation failures also close the prepared native turn. Restart preserves uncertain ownership rather than automatically repeating work.

Cross-language tests use the real Go CLI, Python runtime and local Shell processes in an isolated registered project. They verify default cwd, task state ordering, independent acceptance, cancellation/child stop, workspace reuse, and quarantine after an uncertain cancellation. The provider is an injected fixture; these tests do not contact a real model or a user's coding sessions.

## Remaining work toward the full framework

1. Physical Android acceptance of the integrated chat, keyboard, touch navigation and safe areas; additional executor target controls and system push UI.
2. Extend coding execution to existing Codex/Claude sessions and new projects. Broaden resource recovery for unknown preparation outcomes; never blindly retry an ambiguous launch.
3. Browser/Computer tool adapters, resource leases and artifact storage/backup, including binary MCP results. MCP stdio and Streamable HTTP adapters are implemented; unsupported binary/oversized results stop the call rather than entering model context.
4. Broaden legacy forgetting/re-learning recovery cases; implement provider cache controls and provider/model routing resilience.
5. Proactive triggers/scheduling, notification preferences, quiet hours, rate limits and existing App push delivery adapters. The notification store is implemented, but an outbox row is not proof of external delivery.
6. Broader end-to-end recovery, verification edge cases and real-device acceptance. A single real-provider memory extraction smoke check produced a source-backed candidate without activating it; no latency/cache/cost benchmark has run.

The design and product prototype remain in `docs/design/20261017-agent框架设计/`.

## Provider reference

The streaming adapter follows the official [chat-completions event reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events). It implements this explicit wire contract rather than assuming all provider APIs or models have identical tool/caching capabilities.

## MCP connections

Configure named servers under `[tools.mcp.<name>]` as shown in `agent.example.toml`. A Worker calls `mcp_discover` for the relevant server; Main never waits for MCP startup or carries the full remote catalog. Each connection owns its SDK session in one actor and serializes its calls. Tools use namespaced, schema/version-bound aliases; catalogs are sorted for a stable model prefix. Directory changes remove old tools, and discovery/call refreshes refuse stale aliases before execution. Failed connections back off and reconnect on demand without replaying calls.

Stdio children receive the SDK's minimal default environment plus explicitly mapped `env_env` variables. HTTP credentials come from `key_env` or `header_env`; endpoint URLs cannot carry credentials. Raw server errors/stderr and progress messages do not enter ordinary logs or model context. Numeric progress events are bounded and persisted against the active turn lease. Calls have bounded queues, deadlines and output; cancellation sends a best-effort MCP cancellation notification and closes the connection. A remote cancellation is not proof that a write stopped: ambiguous outcomes are persisted as unknown, end the current turn and never automatically replay. Only explicitly configured `read_only` tools count as reads; server hints alone do not remove verification.

The adapter uses the official [Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0) for the [MCP transports and lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). Automated checks use real stdio processes and an authenticated local Streamable HTTP server, plus native Worker discovery/calls, catalog fingerprints, schema changes, timeouts, cancellation and unknown outcomes. They do not contact configured production MCP services.
