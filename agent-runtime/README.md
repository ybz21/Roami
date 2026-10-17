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

- `storage.py`: SQLite transactions on one dedicated thread; bounded admission; lifetime shared platform maintenance lock and exclusive Agent instance lock; schema/catalog compatibility checks; missing ready database is an error.
- `conversation.py`: owner-scoped conversations, request idempotency, append-only branches, completed-checkpoint Fork and persisted event replay. Recovery preserves partial messages and marks unknown tool outcomes rather than replaying them.
- `runtime.py`: Main/Worker model loops with separate capacity, serialized branches, committed streaming deltas, tools, interruption, shared ancestor step/deadline budgets, descendant joins, verification and result mailbox. Native read-only answers can finish automatically; writes/external results require an injected verifier or explicit acceptance rather than trusting the executor's success claim.
- `memory.py`: source-backed task/conversation/project/day/user scopes, CJK FTS, bounded retrieval, source reads, version replacement, tombstones and snapshot invalidation. Forgetting a memory also suppresses its source in future context projections.
- `context.py`: canonical turn projection separate from transcript append order, persisted manual/automatic compaction, complete-round cuts, paired tools, source/epoch validation, cancellation and immutable transcripts. The current estimate is a conservative UTF-8 byte bound, not a provider tokenizer.
- `providers.py`: configurable streaming chat-completions-compatible adapter; fragmented tool arguments, raw usage and incomplete-stream errors. Endpoint, model and credentials are explicit; no implicit provider or paid account is selected.
- `tasks.py`: idempotent delegation, native child branches, optional checkpoint inheritance, depth/concurrency checks, revision-bound reports, verification queue and cascading cancellation intent. Cancellation intent does not claim an external process has stopped.
- `tools.py` / `process.py`: typed/validated registry; small Main catalog; bounded worker Shell, named HTTP endpoints and on-demand Skills. Shell roots validate cwd and are not an OS filesystem sandbox. External process groups are killed/reaped on cancellation or timeout.
- `server.py` / `main.py`: private HTTP/SSE service, durable event replay, scoped APIs, local callbacks and six slash commands: compact/status/tasks/memory/stop/help.
- `notifications.py`: proactive assistant message + completed event + delivery outbox in one transaction, source-scoped deduplication, unread queries and monotonic per-conversation read watermarks.
- `internal/agentruntime`, `cmd/roami/agent.go`, `backend/server/agent-runtime.go`: unified paths/catalog initialization, CLI, private transport and authenticated public proxy with immediate SSE flushing. Unified database restore rejects unsupported Agent schema versions.

The runtime schema started from the dated design's candidate schema, and additionally includes `conversation_reads`. Python owns the business DDL; Go registers the database and coordinates maintenance. Stop the runtime before unified database backup/layout migration. Current database backup does not yet form a complete Agent artifact recovery package.

## Coding execution transport

`roami agent execution launch --file SPEC.json` launches a one-shot coding process in a new, recorded tmux session. `status --key KEY` returns the durable result; `cancel --key KEY` requests cancellation and must be followed by status to confirm it. A spec contains `key`, `executor` (`codex` or `claude`), `prompt`, `timeoutSeconds` (1–86400), and either an absolute `directory` or a `projectId`. `model`/`permission` are optional; project specs additionally accept `base`/`remote`.

The Go service uses the existing Agent registry, application session service, project store and worktree service. Arguments use argv, prompts use stdin, and private execution receipts live under `<DataRoot>/agents/executions`. It never guesses a Codex conversation ID. A reused key must have exactly the same spec; an unknown launch or interrupted runner is never blindly re-executed. Output remains visible in the session while running, with bounded stdout/stderr tails persisted for retrieval. Coding processes and shared Git workspace operations detach inherited repository bindings (including Git hook context) while retaining Git authentication settings. Timeout, cancellation and shutdown signals terminate the execution process group. The default permission comes from the coding CLI; explicit bypass is only applied when requested in the spec.

`coding_executor.py` connects new loose-session and existing-project tasks to this transport. Set `runtime.coding_directory` explicitly, or provide an absolute `target.directory` for a `new_session` task. Go-launched Python defaults to the same Go executable for CLI calls. Launch returns without occupying a worker for the full coding duration; a separate monitor polls results and records the session binding. External executions have a separate bounded admission count and retain the original task deadline. Python restart observes the original launch; cancellation stays pending until the Go runner returns a terminal result. Missing launch evidence and observation failures are distinct, and uncertain execution is not replayed.

A `project` target uses `projectId`, with optional `base`/`remote`. Go resolves the stable ID (including aliases) through the existing project store, then uses the shared worktree service. Git projects require a successful fetch and create a new checkout from the returned fixed remote OID; local main stays untouched. Directory projects retain their project identity and execute in their existing directory. A caller cannot override a project's directory or silently substitute the loose-session directory. Preparation is journaled under the launch key, bounded to 120 seconds and charged against the same task deadline; retries return the same workspace receipt. Preparation failure saves a failed result and never starts the coding process. Workspaces are preserved on execution failure for inspection.

Python exposes `preparing` until an actual running receipt arrives, persists the resolved target and workspace event, and inherits parent task deadlines. Existing-session continuation, new-project creation, external checkpoint Fork and explicit reuse of an existing project workspace remain required. These targets fail explicitly; callers must not substitute an arbitrary current directory for a project target. External success still enters the verification path; this transport does not equate an exit code with meeting the user's goal.

## Remaining work toward the full framework

1. Real frontend integration while preserving the desktop project/session tree, historical conversations, project quick tasks and mobile navigation. Add unread badge, visible-message read acknowledgements, compression controls and command suggestions.
2. Extend coding execution to existing Codex/Claude sessions, new projects and explicit workspace reuse. Bind native Worker project tools to prepared workspaces as well. Broaden resource recovery for unknown preparation outcomes; never blindly retry an ambiguous launch.
3. MCP, Browser/Computer tool adapters, resource leases and artifact storage/backup. Parsed MCP configuration is not an operational adapter yet.
4. Background memory extraction/daily summaries, complete forgetting propagation, provider cache controls and provider/model routing resilience.
5. Proactive triggers/scheduling, notification preferences, quiet hours, rate limits and existing App push delivery adapters. The notification store is implemented, but an outbox row is not proof of external delivery.
6. Broader end-to-end recovery, verification edge cases and real-device acceptance. No real provider latency/cache/cost benchmark has run.

The design and product prototype remain in `docs/design/20261017-agent框架设计/`.

## Provider reference

The streaming adapter follows the official [chat-completions event reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events). It implements this explicit wire contract rather than assuming all provider APIs or models have identical tool/caching capabilities.
