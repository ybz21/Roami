"""Durable branch actors with separate Main and Worker capacity."""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from .configuration import Settings
from .context import Context
from .conversation import Conversations, message, owned
from .memory import Memories
from .notifications import Notifications
from .storage import Database, DomainError, encoded, event, identity, now_ms, row, rows
from .tasks import Tasks
from .tools import Tool, Tools, add_worker_tools, object_schema

log = logging.getLogger(__name__)
COMMANDS = [
    {
        "name": "compact",
        "description": "Compact current context; optional focus",
        "arguments": True,
    },
    {"name": "status", "description": "Current conversation and runtime status"},
    {"name": "tasks", "description": "Open delegated tasks"},
    {"name": "memory", "description": "Open scoped memories"},
    {"name": "stop", "description": "Interrupt only the current Main reply"},
    {"name": "help", "description": "List slash commands"},
]


class Runtime:
    def __init__(
        self,
        database: Database,
        model,
        *,
        settings=None,
        worker_model=None,
        executor=None,
        verifier: Callable[[dict, dict], Awaitable[bool]] | None = None,
    ):
        self.db, self.model = database, model
        self.settings = settings or Settings()
        self.worker_model = worker_model or model
        self.executor, self.verifier = executor, verifier
        self.conversations = Conversations(database)
        self.memory = Memories(database)
        self.notifications = Notifications(database)
        self.context = Context(database, model, input_budget=self.settings.input_budget)
        self.tasks = Tasks(database, self.conversations, max_depth=self.settings.max_depth)
        self.tools = Tools()
        self.active = {}
        self.active_branches = set()
        self.turn_tasks = {}
        self.wakeup = asyncio.Event()
        self.stopping = False
        self.supervisor = None
        self.external_monitor = None
        self._register_tools()
        add_worker_tools(self.tools, self.settings)

    def _register_tools(self):
        async def delegate(args, binding):
            return await self.tasks.create(
                binding["owner"],
                binding["conversation"],
                args["goal"],
                key=binding["toolCallId"],
                parent_task_id=binding.get("taskId"),
                executor=args.get("executor", "native"),
                target=args.get("target"),
                from_message_id=args.get("fromMessageId"),
                origin_message_id=binding["originMessageId"],
            )

        async def status(args, binding):
            return await self.tasks.list(binding["owner"], binding["conversation"])

        async def recall(args, binding):
            hits = await self.memory.search(
                binding["owner"],
                args["query"],
                conversation_id=binding["conversation"]
                if args.get("scope", "conversation") == "conversation"
                else None,
                project_id=args.get("projectId"),
                limit=8,
            )
            result, remaining = [], 6000
            for hit in hits:
                excerpt = hit["body"][:500]
                item = {
                    "id": hit["id"],
                    "title": hit["title"],
                    "excerpt": excerpt,
                    "revision": hit["revision"],
                }
                size = len(encoded(item).encode())
                if size > remaining:
                    break
                result.append(item)
                remaining -= size
            return result

        async def recall_one(args, binding):
            hit = await self.memory.get(binding["owner"], args["memoryId"])
            offset = args.get("offset", 0)
            return {
                "id": hit["id"],
                "title": hit["title"],
                "body": hit["body"][offset : offset + 2000],
                "sources": hit["sources"],
                "nextOffset": offset + 2000 if len(hit["body"]) > offset + 2000 else None,
            }

        self.tools.add(
            Tool(
                "memory_get",
                "Read a source-backed memory in bounded pages.",
                object_schema(
                    {"memoryId": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
                    ["memoryId"],
                ),
                recall_one,
                main=True,
            )
        )

        self.tools.add(
            Tool(
                "delegate",
                "Delegate long work; returns a task immediately. Use fromMessageId only for a completed checkpoint Fork.",
                object_schema(
                    {
                        "goal": {"type": "string", "minLength": 1, "maxLength": 20000},
                        "executor": {"type": "string", "enum": ["native", "codex", "claude"]},
                        "target": {"type": "object"},
                        "fromMessageId": {"type": "string"},
                    },
                    ["goal"],
                ),
                delegate,
                effect="write",
                main=True,
            )
        )
        self.tools.add(
            Tool("task_status", "Read delegated task status.", object_schema({}), status, main=True)
        )
        self.tools.add(
            Tool(
                "memory_search",
                "Retrieve source-backed memories only when relevant.",
                object_schema(
                    {
                        "query": {"type": "string", "maxLength": 1000},
                        "scope": {"type": "string", "enum": ["conversation", "user"]},
                        "projectId": {"type": "string"},
                    },
                    ["query"],
                ),
                recall,
                main=True,
            )
        )

    async def start(self):
        await self.conversations.recover()
        await self._recover_tasks()
        self.supervisor = asyncio.create_task(self._supervise(), name="roami-agent-supervisor")
        if self.executor and getattr(self.executor, "can_reconcile", False):
            self.external_monitor = asyncio.create_task(self._monitor_external())
        self.wakeup.set()

    async def _monitor_external(self):
        while not self.stopping:
            try:
                await self.executor.poll(self.tasks)
                self.wakeup.set()
            except (DomainError, OSError, TimeoutError):
                log.exception("External executor observation failed")
            await asyncio.sleep(1)

    async def close(self):
        self.stopping = True
        self.wakeup.set()
        if self.supervisor:
            await self.supervisor
        if self.external_monitor:
            self.external_monitor.cancel()
            await asyncio.gather(self.external_monitor, return_exceptions=True)
        running = [item["handle"] for item in self.active.values()]
        for handle in running:
            handle.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    async def submit(self, owner, cid, request_key, text):
        parts = text.strip().split(maxsplit=1)
        command, arguments = (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")
        if text.strip().startswith("/") and "\n" not in text.strip():
            name = command[1:]
            if name not in {c["name"] for c in COMMANDS}:
                raise DomainError("UNKNOWN_COMMAND")
            if name != "compact" and arguments.strip():
                raise DomainError("UNEXPECTED_COMMAND_ARGUMENTS")
            await self.conversations.get(owner, cid)
            if name == "compact":
                job = await self.context.request(owner, cid, request_key, arguments.strip())
                self.wakeup.set()
                return {"kind": "compaction", "operationId": job["id"], "state": job["state"]}
            if name == "stop":
                return await self.interrupt(owner, cid, request_key)
            if name == "help":
                return {"kind": "commands", "commands": COMMANDS}
            if name == "status":
                return await self.status(owner, cid)
            return {"kind": "ui_action", "action": name, "conversationId": cid}
        if not self.model.model:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        result = await self.conversations.accept(owner, cid, request_key, text)
        self.wakeup.set()
        return {"kind": "message", **result}

    async def status(self, owner, cid):
        plan = await self.context.project(owner, cid)
        return {
            "kind": "status",
            "model": self.model.model,
            "conversationId": cid,
            "context": {k: v for k, v in plan.items() if k != "messages"},
            "tasks": await self.tasks.list(owner, cid),
            "writerBacklog": self.db.pending,
        }

    async def interrupt(self, owner, cid, request_key):
        digest = hashlib.sha256(encoded(["stop", cid]).encode()).hexdigest()

        def write(db):
            c = owned(db, owner, cid)
            old = row(
                db,
                "SELECT * FROM requests WHERE owner_id=? AND request_key=?",
                (owner, request_key),
            )
            if old:
                if old["payload_sha256"] != digest:
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                receipt = row(
                    db,
                    "SELECT payload_json FROM jobs WHERE kind='control.stop' AND aggregate_id=?",
                    (old["id"],),
                )
                return json.loads(receipt["payload_json"])
            turn = row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state='running'",
                (c["active_branch_id"],),
            )
            result = {"kind": "interrupt", "turnId": turn["id"] if turn else None}
            rid = identity()
            db.execute(
                "INSERT INTO requests(id,owner_id,request_key,payload_sha256,conversation_id,accepted_ms) VALUES(?,?,?,?,?,?)",
                (rid, owner, request_key, digest, cid, now_ms()),
            )
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'control.stop',?,?,?,'done',?)",
                (identity(), rid, rid, encoded(result), now_ms()),
            )
            return result

        result = await self.db.call(write, write=True)
        handle = self.turn_tasks.get(result["turnId"])
        if handle:
            handle.cancel()
        return result

    async def _supervise(self):
        while not self.stopping:
            self.wakeup.clear()
            try:
                await self._scan()
                await self._cancel_tasks()
            except (DomainError, OSError):
                log.exception("Agent supervisor iteration failed")
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=0.1)
            except TimeoutError:
                pass

    async def _scan(self):
        queued = await self.db.call(
            lambda db: rows(
                db,
                "SELECT j.*,t.branch_id,b.id AS native_branch_id,a.executor_kind FROM jobs j "
                "LEFT JOIN turns t ON j.kind='turn.run' AND t.id=j.aggregate_id "
                "LEFT JOIN task_attempts a ON j.kind='task.run' AND a.id=json_extract(j.payload_json,'$.runId') "
                "LEFT JOIN branches b ON b.id=a.native_branch_id "
                "WHERE j.state='queued' AND j.kind IN ('turn.run','context.compact','task.run','task.verify') "
                "AND j.available_ms<=? ORDER BY CASE j.kind WHEN 'turn.run' THEN 0 ELSE 1 END,j.rowid LIMIT 100",
                (now_ms(),),
            )
        )
        external_running = await self.db.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM tasks t JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision "
                "WHERE a.executor_kind='cli' AND t.state IN ('running','cancelling')"
            ).fetchone()[0]
        )
        for job in queued:
            if job["id"] in self.active:
                continue
            group = "main" if job["kind"] == "turn.run" else "worker"
            capacity = self.settings.main_concurrency if group == "main" else self.settings.workers
            if sum(v["group"] == group for v in self.active.values()) >= capacity:
                continue
            if job.get("executor_kind") == "cli":
                if external_running >= self.settings.workers:
                    continue
                external_running += 1
            branch = job.get("branch_id") or job.get("native_branch_id")
            if job["kind"] == "context.compact":
                branch = json.loads(job["payload_json"])["branchId"]
            if branch and branch in self.active_branches:
                continue
            if branch:
                self.active_branches.add(branch)
            handle = asyncio.create_task(self._job(job), name="agent-job-" + job["id"])
            self.active[job["id"]] = {
                "handle": handle,
                "group": group,
                "branch": branch,
                "task": job["aggregate_id"] if job["kind"] == "task.run" else None,
            }
            handle.add_done_callback(lambda _, key=job["id"]: self._finished(key))

    def _finished(self, key):
        item = self.active.pop(key, None)
        if item and item["branch"]:
            self.active_branches.discard(item["branch"])
        self.wakeup.set()

    async def _job(self, job):
        try:
            if job["kind"] == "context.compact":
                await self.context.run(job["id"])
                return
            if job["kind"] == "turn.run":
                turn = await self._claim_turn(job)
                if turn:
                    await self._run_turn(
                        turn, "main", completion=json.loads(job["payload_json"]).get("completion")
                    )
            elif job["kind"] == "task.run":
                await self._run_task(job)
            elif job["kind"] == "task.verify":
                await self._verify_task(job)
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='done' WHERE id=? AND state='running'", (job["id"],)
                ),
                write=True,
            )
        except asyncio.CancelledError:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='failed' WHERE id=? AND state='running'", (job["id"],)
                ),
                write=True,
            )
            raise
        except Exception:
            # Every admitted job must have a durable terminal outcome, including programming failures.
            log.exception("Agent job failed: %s", job["id"])
            await self.db.call(
                lambda db: db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job["id"],)),
                write=True,
            )

    async def _claim_turn(self, job):
        def write(db):
            turn = row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=? AND t.state='queued'",
                (job["aggregate_id"],),
            )
            if not turn:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                return None
            if row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state='running'",
                (turn["branch_id"],),
            ):
                return None
            db.execute(
                "UPDATE turns SET state='running',lease_epoch=lease_epoch+1 WHERE id=?",
                (turn["id"],),
            )
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?", (job["id"],)
            )
            return turn

        return await self.db.call(write, write=True)

    async def _run_turn(self, turn, role, *, task_id=None, completion=None):
        tid, cid, owner = (turn[k] for k in ["id", "conversation_id", "owner_id"])
        self.turn_tasks[tid] = asyncio.current_task()
        model = self.model if role == "main" else self.worker_model
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                instructions = (
                    self.settings.main_instructions
                    if role == "main"
                    else self.settings.worker_instructions
                )
                catalog = self.tools.catalog(role)
                plan, prompt = await self._prompt(turn, instructions, catalog, completion)
                origin = await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM messages WHERE turn_id=? AND role='user' ORDER BY seq LIMIT 1",
                        (tid,),
                    )
                )
                for step in range(self.settings.max_steps):
                    if task_id:
                        await self._charge_task(task_id)
                    wire_hash = hashlib.sha256(encoded([prompt, catalog]).encode()).hexdigest()
                    await self.db.call(
                        lambda db, step=step, wire_hash=wire_hash, plan=plan: db.execute(
                            "INSERT INTO prompt_manifests(id,turn_id,attempt_no,provider_key,model_key,serializer_version,prefix_sha256,snapshot_id,memory_epoch,parts_json,created_ms) "
                            "VALUES(?,?,?,?,?,'chat-v1',?,?,1,?,?)",
                            (
                                identity(),
                                tid,
                                step + 1,
                                "chat-completions",
                                model.model,
                                wire_hash,
                                plan["snapshotId"],
                                encoded(
                                    {
                                        "role": role,
                                        "catalogHash": hashlib.sha256(
                                            encoded(catalog).encode()
                                        ).hexdigest(),
                                    }
                                ),
                                now_ms(),
                            ),
                        ),
                        write=True,
                    )
                    mid = await self._assistant_start(turn)
                    text, calls, usage, buffer, flushed = "", [], None, "", time.monotonic()
                    async for part in model.stream(prompt, catalog):
                        if part.kind == "text":
                            text += part.value
                            buffer += part.value
                            if len(text) > 100_000:
                                raise DomainError("MODEL_OUTPUT_LIMIT")
                            if len(buffer.encode()) >= 1024 or time.monotonic() - flushed >= 0.1:
                                await self._delta(turn, mid, text, buffer)
                                buffer, flushed = "", time.monotonic()
                        elif part.kind == "tool":
                            calls.append(part.value)
                        elif part.kind == "usage":
                            usage = part.value
                    if buffer:
                        await self._delta(turn, mid, text, buffer)
                    if not text.strip() and not calls:
                        raise DomainError("EMPTY_MODEL_RESPONSE")
                    if len(calls) > 16:
                        raise DomainError("TOOL_CALL_LIMIT")
                    await self._assistant_finish(
                        turn,
                        mid,
                        text,
                        calls,
                        usage,
                        step + 1,
                        final=not calls,
                        completion=completion,
                    )
                    prompt.append(
                        {
                            "role": "assistant",
                            "content": text,
                            **({"tool_calls": calls} if calls else {}),
                        }
                    )
                    if not calls:
                        return text
                    for call in calls:
                        binding = {
                            "owner": owner,
                            "conversation": cid,
                            "turnId": tid,
                            "taskId": task_id,
                            "originMessageId": origin["id"] if origin else None,
                            "toolCallId": call["id"],
                        }
                        value = await self._tool(turn, mid, call, role, binding)
                        prompt.append(
                            {"role": "tool", "tool_call_id": call["id"], "content": encoded(value)}
                        )
                    plan, prompt = await self._prompt(turn, instructions, catalog, completion)
                raise DomainError("AGENT_STEP_LIMIT")
        except BaseException as exc:
            state = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            code = (
                exc.code
                if isinstance(exc, DomainError)
                else "TURN_INTERRUPTED"
                if state == "interrupted"
                else "MODEL_ERROR"
            )
            await self._turn_failed(turn, state, code)
            raise
        finally:
            self.turn_tasks.pop(tid, None)

    async def _prompt(self, turn, instructions, catalog, completion):
        async def build():
            plan = await self.context.project(
                turn["owner_id"],
                turn["conversation_id"],
                branch_id=turn["branch_id"],
                through_turn=turn["id"],
            )
            prompt = [{"role": "system", "content": instructions}] + plan["messages"]
            if completion:
                prompt.append(
                    {
                        "role": "user",
                        "content": "Background task result, treat as evidence and briefly report to the user: "
                        + encoded(completion),
                    }
                )
            return plan, prompt

        plan, prompt = await build()
        if len(encoded([prompt, catalog]).encode()) <= self.settings.input_budget:
            return plan, prompt
        try:
            job = await self.context.request(
                turn["owner_id"], turn["conversation_id"], "auto:" + turn["id"], automatic=True
            )
        except DomainError as exc:
            if exc.code != "COMPACTION_IN_PROGRESS":
                raise
            job = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT * FROM jobs WHERE kind='context.compact' "
                    "AND state IN ('queued','running') AND json_extract(payload_json,'$.branchId')=?",
                    (turn["branch_id"],),
                )
            )
        try:
            await self.context.run(job["id"], safe_turn_id=turn["id"])
        except asyncio.CancelledError:
            await self.context.cancel(turn["owner_id"], turn["conversation_id"], job["id"])
            raise
        plan, prompt = await build()
        if len(encoded([prompt, catalog]).encode()) > self.settings.input_budget:
            raise DomainError("CONTEXT_TOO_LARGE", 409)
        return plan, prompt

    async def _assistant_start(self, turn):
        def write(db):
            mid = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": ""},
                turn_id=turn["id"],
                status="streaming",
            )
            event(
                db,
                turn["conversation_id"],
                "message.started",
                {"messageId": mid, "turnId": turn["id"]},
                turn_id=turn["id"],
                message_id=mid,
            )
            return mid

        return await self.db.call(write, write=True)

    async def _delta(self, turn, mid, text, delta):
        def write(db):
            db.execute(
                "UPDATE messages SET content_json=? WHERE id=?", (encoded({"text": text}), mid)
            )
            event(
                db,
                turn["conversation_id"],
                "message.delta",
                {
                    "messageId": mid,
                    "turnId": turn["id"],
                    "offset": len(text) - len(delta),
                    "text": delta,
                },
                turn_id=turn["id"],
                message_id=mid,
            )

        await self.db.call(write, write=True)

    async def _assistant_finish(self, turn, mid, text, calls, usage, attempt, *, final, completion):
        def write(db):
            content = {"text": text, **({"tool_calls": calls} if calls else {})}
            if completion:
                content["source"] = "task"
            db.execute(
                "UPDATE messages SET content_json=?,status='completed' WHERE id=?",
                (encoded(content), mid),
            )
            db.execute(
                "UPDATE prompt_manifests SET usage_json=? WHERE turn_id=? AND attempt_no=?",
                (encoded(usage) if usage else None, turn["id"], attempt),
            )
            if final:
                db.execute(
                    "UPDATE turns SET state='completed',finished_ms=? WHERE id=?",
                    (now_ms(), turn["id"]),
                )
                cursor = event(
                    db,
                    turn["conversation_id"],
                    "message.completed",
                    {
                        "messageId": mid,
                        "turnId": turn["id"],
                        "source": "task" if completion else "main",
                    },
                    turn_id=turn["id"],
                    message_id=mid,
                )
                for binding in rows(
                    db,
                    "SELECT id FROM channel_bindings WHERE conversation_id=? AND enabled=1",
                    (turn["conversation_id"],),
                ):
                    db.execute(
                        "INSERT INTO deliveries(id,event_id,channel_id,state) VALUES(?,?,?,'pending')",
                        (identity(), cursor, binding["id"]),
                    )
            else:
                event(
                    db,
                    turn["conversation_id"],
                    "message.tool_calls",
                    {"messageId": mid, "calls": calls},
                    turn_id=turn["id"],
                    message_id=mid,
                )

        await self.db.call(write, write=True)

    async def _tool(self, turn, mid, call, role, binding):
        try:
            tool, args = self.tools.validate(call, role)
        except (DomainError, KeyError, TypeError):
            tool, args = None, {}
        tool_id = identity()
        await self.db.call(
            lambda db: db.execute(
                "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) "
                "VALUES(?,?,?,?,?,?,'planned',?,?,?)",
                (
                    tool_id,
                    turn["id"],
                    mid,
                    call["function"]["name"],
                    encoded(args),
                    tool.effect if tool else "read",
                    turn["id"] + ":" + call["id"],
                    now_ms(),
                    now_ms(),
                ),
            ),
            write=True,
        )
        try:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE tool_calls SET state='running' WHERE id=?", (tool_id,)
                ),
                write=True,
            )
            value = await self.tools.invoke(call, role, binding)
            state = "succeeded"
        except (DomainError, TimeoutError, OSError, httpx.HTTPError) as exc:
            value = {"error": exc.code if isinstance(exc, DomainError) else "TOOL_FAILED"}
            state = "failed"
        except asyncio.CancelledError:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE tool_calls SET state='unknown',updated_ms=? WHERE id=?",
                    (now_ms(), tool_id),
                ),
                write=True,
            )
            raise

        def finish(db):
            result_id = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "tool",
                {"text": encoded(value), "tool_call_id": call["id"]},
                turn_id=turn["id"],
            )
            db.execute(
                "UPDATE tool_calls SET state=?,result_message_id=?,updated_ms=? WHERE id=?",
                (state, result_id, now_ms(), tool_id),
            )
            event(
                db,
                turn["conversation_id"],
                "tool.completed",
                {"toolCallId": tool_id, "state": state},
                turn_id=turn["id"],
            )

        await self.db.call(finish, write=True)
        self.wakeup.set()
        return value

    async def _turn_failed(self, turn, state, code):
        def write(db):
            db.execute(
                "UPDATE turns SET state=?,finished_ms=? WHERE id=? AND state='running'",
                (state, now_ms(), turn["id"]),
            )
            db.execute(
                "UPDATE messages SET status=? WHERE turn_id=? AND status='streaming'",
                (state, turn["id"]),
            )
            event(
                db,
                turn["conversation_id"],
                "turn." + state,
                {"turnId": turn["id"], "error": code},
                turn_id=turn["id"],
            )

        await self.db.call(write, write=True)

    async def _charge_task(self, task_id):
        def write(db):
            task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))
            current = task
            while current:
                budget = json.loads(current["budget_json"])
                budget["usedSteps"] = budget.get("usedSteps", 0) + 1
                if budget["usedSteps"] > budget["maxTurns"] or now_ms() >= budget["deadlineMs"]:
                    raise DomainError("TASK_BUDGET_EXCEEDED")
                if current["state"] == "cancelling":
                    raise DomainError("TASK_CANCELLING")
                db.execute(
                    "UPDATE tasks SET budget_json=? WHERE id=?", (encoded(budget), current["id"])
                )
                current = (
                    row(db, "SELECT * FROM tasks WHERE id=?", (current["parent_task_id"],))
                    if current["parent_task_id"]
                    else None
                )

        await self.db.call(write, write=True)

    async def _run_task(self, job):
        def start(db):
            task = row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
            run = row(
                db,
                "SELECT * FROM task_attempts WHERE id=?",
                (json.loads(job["payload_json"])["runId"],),
            )
            if task["state"] != "queued" or run["state"] != "accepted":
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                return None
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?", (job["id"],)
            )
            db.execute(
                "UPDATE tasks SET state='running',updated_ms=? WHERE id=?", (now_ms(), task["id"])
            )
            db.execute(
                "UPDATE task_attempts SET state='running',started_ms=? WHERE id=?",
                (now_ms(), run["id"]),
            )
            turn = None
            if run["executor_kind"] == "native":
                b = row(db, "SELECT * FROM branches WHERE id=?", (run["native_branch_id"],))
                tid = identity()
                db.execute(
                    "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'user','running',?)",
                    (tid, b["conversation_id"], b["id"], now_ms()),
                )
                db.execute(
                    "UPDATE messages SET turn_id=? WHERE branch_id=? AND turn_id IS NULL",
                    (tid, b["id"]),
                )
                turn = dict(
                    row(db, "SELECT * FROM turns WHERE id=?", (tid,)), owner_id=task["owner_id"]
                )
            event(
                db,
                task["origin_conversation_id"],
                "task.started",
                {"taskId": task["id"], "runId": run["id"]},
                task_id=task["id"],
            )
            return task, run, turn

        started = await self.db.call(start, write=True)
        if not started:
            return
        task, run, turn = started
        try:
            if turn:
                text = await self._run_turn(turn, "worker", task_id=task["id"])
                result = {"state": "succeeded", "summary": text}
            elif self.executor:
                await self._charge_task(task["id"])
                result = await self.executor.run(task, run)
                if result is None:  # External TUI is alive; report arrives via the CLI callback.
                    return
            else:
                raise DomainError("EXTERNAL_EXECUTOR_NOT_CONFIGURED")
        except asyncio.CancelledError:
            if run["executor_kind"] == "cli" and getattr(self.executor, "can_reconcile", False):
                # The Go runner outlives Python; restart observes the same launch key.
                raise
            current = await self.db.call(
                lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
            )
            if current["state"] == "cancelling":
                await self.tasks.report(
                    task["owner_id"],
                    task["id"],
                    run["id"],
                    task["revision"],
                    {"state": "cancelled", "summary": "Cancelled"},
                )
            else:
                await self.db.call(
                    lambda db: db.execute(
                        "UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],)
                    ),
                    write=True,
                )
            raise
        except (DomainError, OSError, ValueError, httpx.HTTPError, TimeoutError) as exc:
            result = {
                "state": "failed",
                "summary": exc.code if isinstance(exc, DomainError) else "EXECUTION_FAILED",
            }
        await self.tasks.report(task["owner_id"], task["id"], run["id"], task["revision"], result)

    async def _verify_task(self, job):
        task = await self.db.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
        )
        run = await self.db.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE id=?",
                (json.loads(job["payload_json"])["runId"],),
            )
        )
        if not task or task["revision"] != run["task_revision"]:
            await self.db.call(
                lambda db: db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],)),
                write=True,
            )
            return
        children = await self.db.call(
            lambda db: rows(db, "SELECT * FROM tasks WHERE parent_task_id=?", (task["id"],))
        )
        if any(
            c["state"] not in {"succeeded", "failed", "cancelled", "interrupted"} for c in children
        ):
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET available_ms=? WHERE id=?", (now_ms() + 100, job["id"])
                ),
                write=True,
            )
            return
        result = json.loads(run["result_json"])
        if children:
            result["children"] = [
                {
                    "taskId": c["id"],
                    "state": c["state"],
                    "goal": json.loads(c["intent_json"])["goal"],
                    "result": await self.db.call(
                        lambda db, c=c: row(
                            db,
                            "SELECT result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                            (c["id"],),
                        )
                    ),
                }
                for c in children
            ]
            if any(c["state"] != "succeeded" for c in children):
                result["state"] = "failed"
        verified = False
        if result["state"] == "succeeded":
            if self.verifier:
                verified = await self.verifier(task, result)
            else:
                # Native read-only answers can finish; writes require explicit acceptance.
                writes = await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT x.id FROM tool_calls x JOIN turns t ON t.id=x.turn_id WHERE t.branch_id=? AND x.effect='write' AND x.tool_name!='delegate' LIMIT 1",
                        (run["native_branch_id"],),
                    )
                )
                verified = (
                    run["executor_kind"] == "native"
                    and not writes
                    and bool(result.get("summary", "").strip())
                )
        state = (
            result["state"]
            if result["state"] != "succeeded"
            else "succeeded"
            if verified
            else "waiting_user"
        )
        await self._complete_task(task, run, result, state, job_id=job["id"])

    async def _complete_task(self, task, run, result, state, *, job_id=None):
        def write(db):
            current = row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
            if current["revision"] != run["task_revision"] or current["state"] in {
                "cancelled",
                "interrupted",
            }:
                if job_id:
                    db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
                return
            completion = {"taskId": task["id"], "state": state, "result": result}
            db.execute(
                "UPDATE tasks SET state=?,updated_ms=? WHERE id=?", (state, now_ms(), task["id"])
            )
            key = "task.completion:" + run["id"] + ":" + state
            if task["parent_task_id"]:
                event(
                    db,
                    task["origin_conversation_id"],
                    "task." + state,
                    completion,
                    task_id=task["id"],
                )
                if job_id:
                    db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
                return
            if not row(db, "SELECT id FROM jobs WHERE dedupe_key=?", (key,)):
                tid = identity()
                db.execute(
                    "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'completion','queued',?)",
                    (tid, task["origin_conversation_id"], task["origin_branch_id"], now_ms()),
                )
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'turn.run',?,?,?,'queued',?)",
                    (identity(), tid, key, encoded({"completion": completion}), now_ms()),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task." + state,
                    completion,
                    task_id=task["id"],
                )
            if job_id:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))

        await self.db.call(write, write=True)

    async def confirm(self, owner, task_id, accepted):
        task = await self.db.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
        )
        if not task:
            raise DomainError("TASK_NOT_FOUND", 404)
        if task["state"] != "waiting_user":
            raise DomainError("TASK_NOT_WAITING_VERIFICATION", 409)
        run = await self.db.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                (task_id, task["revision"]),
            )
        )
        await self._complete_task(
            task, run, json.loads(run["result_json"]), "succeeded" if accepted else "failed"
        )
        self.wakeup.set()
        return {"taskId": task_id, "state": "succeeded" if accepted else "failed"}

    async def _cancel_tasks(self):
        cancelling = await self.db.call(
            lambda db: rows(db, "SELECT * FROM tasks WHERE state='cancelling'")
        )
        for task in cancelling:
            active = next((a for a in self.active.values() if a["task"] == task["id"]), None)
            if active and getattr(self.executor, "can_reconcile", False):
                attempt = await self.db.call(
                    lambda db, task=task: row(
                        db,
                        "SELECT executor_kind FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                        (task["id"],),
                    )
                )
                if attempt and attempt["executor_kind"] == "cli":
                    continue
            if active:
                if not active["handle"].cancelling():
                    active["handle"].cancel()
            else:
                run = await self.db.call(
                    lambda db, task=task: row(
                        db,
                        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                        (task["id"], task["revision"]),
                    )
                )
                if run["state"] == "accepted":
                    await self.tasks.report(
                        task["owner_id"],
                        task["id"],
                        run["id"],
                        task["revision"],
                        {"state": "cancelled", "summary": "Cancelled before start"},
                    )
                elif (
                    run["executor_kind"] == "cli"
                    and self.executor
                    and not getattr(self.executor, "can_reconcile", False)
                ):
                    await self.executor.cancel(task, run)

    async def _recover_tasks(self):
        def write(db):
            for task in rows(db, "SELECT * FROM tasks WHERE state='running'"):
                external = row(
                    db,
                    "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? AND executor_kind='cli' AND result_json IS NULL",
                    (task["id"], task["revision"]),
                )
                if external and getattr(self.executor, "can_reconcile", False):
                    db.execute(
                        "UPDATE task_attempts SET state='unknown' WHERE id=?", (external["id"],)
                    )
                    db.execute(
                        "UPDATE jobs SET state='done' WHERE kind='task.run' AND aggregate_id=?",
                        (task["id"],),
                    )
                    continue
                db.execute(
                    "UPDATE task_attempts SET state='unknown' WHERE task_id=? AND state IN ('starting','running')",
                    (task["id"],),
                )
                db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
                db.execute(
                    "UPDATE jobs SET state='failed' WHERE kind='task.run' AND aggregate_id=?",
                    (task["id"],),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.interrupted",
                    {"taskId": task["id"], "reason": "runtime_restart"},
                    task_id=task["id"],
                )

        await self.db.call(write, write=True)
