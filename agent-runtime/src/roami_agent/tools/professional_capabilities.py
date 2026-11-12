"""Task-scoped access to the platform registry for managed professional executors."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import stat
import tempfile

import httpx

from roami_agent.context.execution_brief import execution_prompt
from roami_agent.conversation.activity_events import activity_event
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row
from roami_agent.tools.market_commands import MARKET_OPERATIONS


class ProfessionalCapabilities:
    def __init__(self, runtime):
        self.runtime, self.db = runtime, runtime.db
        self.active = set()
        self.requests = set()
        self.closed = False

    async def recover(self):
        def write(db):
            db.execute(
                "INSERT INTO events(conversation_id,task_id,kind,payload_json,event_key,created_ms) "
                "SELECT s.conversation_id,s.task_id,'capability.completed',"
                "json_object('state','unknown','result',json_object('error','TOOL_OUTCOME_UNKNOWN'),"
                "'requestId',json_extract(s.payload_json,'$.requestId'),'finishedMs',?),"
                "substr(s.event_key,1,length(s.event_key)-6)||':result',? FROM events s "
                "WHERE s.kind='capability.started' AND NOT EXISTS (SELECT 1 FROM events r "
                "WHERE r.event_key=substr(s.event_key,1,length(s.event_key)-6)||':result')",
                (now_ms(), now_ms()),
            )

        await self.db.call(write, write=True)

    def private_directory(self):
        root = self.db.data_root / "agents"
        target = root / "capability-contexts"
        for path in (root, target):
            path.mkdir(exist_ok=True, mode=0o700)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("CAPABILITY_CONTEXT_PRIVATE_FILE_REQUIRED", 503)
        return target

    def signing_key(self):
        path = self.private_directory() / "signing-key"
        try:
            with path.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(secrets.token_bytes(32))
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size != 32
            ):
                raise DomainError("CAPABILITY_CONTEXT_PRIVATE_FILE_REQUIRED", 503)
            return source.read()

    def signature(self, context):
        return hmac.new(self.signing_key(), encoded(context).encode(), hashlib.sha256).hexdigest()

    async def brief(self, task, run):
        context = {
            "taskId": task["id"],
            "runId": run["id"],
            "revision": run["task_revision"],
            "owner": task["owner_id"],
        }
        await self.db.call(lambda db: self.admitted(db, context, task["owner_id"], preparing=True))
        context["signature"] = self.signature(context)
        path = self.private_directory() / (hashlib.sha256(run["id"].encode()).hexdigest() + ".json")
        descriptor, temporary = tempfile.mkstemp(prefix=".context-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(encoded(context))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return (
            "\n\n"
            + execution_prompt("agent-capabilities.md")
            + "\n\n当前任务的能力调用参数（与命令放在同一 shell）：\n\n"
            "```bash\n"
            f"ROAMI_BIN={shlex.quote(self.runtime.settings.cli_bin)}\n"
            f"ROAMI_TASK_CONTEXT={shlex.quote(str(path))}\n"
            "```\n\n"
            '上述 `roami` 使用 `"$ROAMI_BIN"`。读取 Skill、调用能力时带 '
            '`--context "$ROAMI_TASK_CONTEXT"`；调用再带 '
            "`--call REQUEST_ID`。按目录返回的名称与 inputSchema 调用；MCP 未列工具时先 mcp_discover。"
            "上下文不外传，同次重试保留请求 ID，未知结果不换 ID 重放。"
        )

    @staticmethod
    def admitted(db, context, owner, *, preparing=False):
        task = row(
            db,
            "SELECT t.*,a.state AS attempt_state,a.executor_kind,a.finished_ms "
            "FROM tasks t JOIN task_attempts a ON a.task_id=t.id "
            "JOIN conversations c ON c.id=t.origin_conversation_id "
            "JOIN messages m ON m.id=t.origin_message_id "
            "WHERE t.id=? AND a.id=? AND t.revision=? AND a.task_revision=t.revision "
            "AND t.owner_id=? AND c.owner_id=t.owner_id AND c.deleted_ms IS NULL "
            "AND m.deleted_ms IS NULL",
            (context["taskId"], context["runId"], context["revision"], owner),
        )
        states = {"preparing", "running"} if preparing else {"running"}
        if (
            not task
            or task["executor_kind"] != "cli"
            or task["state"] not in states
            or task["attempt_state"] not in ({"starting", "running"} if preparing else {"running"})
            or task["finished_ms"] is not None
            or row(
                db,
                "SELECT 1 FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND state='queued'",
                (task["id"],),
            )
        ):
            raise DomainError("ACTIVE_TASK_CONTEXT_REQUIRED", 409)
        if row(
            db,
            "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
            (owner, task["origin_message_id"]),
        ):
            raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
        budget = json.loads(task["budget_json"])
        if budget.get("deadlineMs") and budget["deadlineMs"] <= now_ms():
            raise DomainError("TASK_BUDGET_EXCEEDED", 409)
        return task

    async def call(self, name, payload, owner):
        request = asyncio.current_task()
        self.requests.add(request)
        try:
            return await self.invoke(name, payload, owner)
        finally:
            self.requests.discard(request)

    async def invoke(self, name, payload, owner):
        if self.closed:
            raise DomainError("RUNTIME_CLOSED", 503)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"executionContext", "requestId", "arguments"}
            or not isinstance(payload["arguments"], dict)
            or not isinstance(payload["requestId"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", payload["requestId"])
        ):
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        context = payload["executionContext"]
        if (
            not isinstance(context, dict)
            or set(context) != {"taskId", "runId", "revision", "owner", "signature"}
            or not all(
                isinstance(context[k], str) for k in ("taskId", "runId", "owner", "signature")
            )
            or type(context["revision"]) is not int
            or context["owner"] != owner
            or not re.fullmatch(r"[a-f0-9]{64}", context["signature"])
            or not hmac.compare_digest(
                context["signature"],
                self.signature({k: v for k, v in context.items() if k != "signature"}),
            )
        ):
            raise DomainError("ACTIVE_TASK_CONTEXT_REQUIRED", 409)
        tool = self.runtime.tools.registry.get(name)
        if not tool or (
            tool.source != "external"
            and name not in {"skill_read", "mcp_discover"} | MARKET_OPERATIONS
        ):
            raise DomainError("TOOL_UNAVAILABLE", 409)
        wire = {"function": {"name": name, "arguments": encoded(payload["arguments"])}}
        request_key = hashlib.sha256(
            (context["runId"] + ":" + payload["requestId"]).encode()
        ).hexdigest()
        key = "capability:" + request_key

        def plan(db):
            task = self.admitted(db, context, owner)
            self.runtime.tools.validate(wire, "worker")
            previous = row(
                db, "SELECT payload_json FROM events WHERE event_key=?", (key + ":start",)
            )
            if previous:
                started = json.loads(previous["payload_json"])
                if started["name"] != name or started["arguments"] != payload["arguments"]:
                    raise DomainError("CAPABILITY_REQUEST_CONFLICT", 409)
                result = row(
                    db, "SELECT payload_json FROM events WHERE event_key=?", (key + ":result",)
                )
                if not result:
                    raise DomainError("TOOL_OUTCOME_UNKNOWN", 409)
                return task, json.loads(result["payload_json"])
            if (
                db.execute(
                    "SELECT count(*) FROM events WHERE task_id=? AND kind='capability.started'",
                    (task["id"],),
                ).fetchone()[0]
                >= 1024
            ):
                raise DomainError("CAPABILITY_CALL_LIMIT", 409)
            event(
                db,
                task["origin_conversation_id"],
                "capability.started",
                {
                    "name": name,
                    "arguments": payload["arguments"],
                    "effect": tool.effect,
                    "runId": context["runId"],
                    "requestId": payload["requestId"],
                },
                key=key + ":start",
                task_id=task["id"],
            )
            activity_event(
                db,
                task["origin_conversation_id"],
                "task.activity",
                {"taskId": task["id"], "activityId": key},
                task_id=task["id"],
            )
            return task, None

        task, previous = await self.db.call(plan, write=True)
        if previous is not None:
            return previous
        self.runtime.wakeup.set()
        if len(self.active) >= 16:
            result = {"state": "failed", "result": {"error": "CAPABILITY_CALL_CAPACITY"}}
        else:
            binding = {
                "owner": owner,
                "conversation": task["origin_conversation_id"],
                "originMessageId": task["origin_message_id"],
                "taskId": task["id"],
                "runId": context["runId"],
                "toolCallId": request_key,
                "workspace": (json.loads(task["target_json"] or "{}") or {}).get("workspace"),
            }
            operation = asyncio.create_task(self.runtime.tools.invoke(wire, "worker", binding))
            self.active.add(operation)
            try:
                async with asyncio.timeout(90):
                    while not operation.done():
                        await asyncio.wait({operation}, timeout=0.25)
                        await self.db.call(lambda db: self.admitted(db, context, owner))
                    value = await operation
                failed = isinstance(value, dict) and (
                    value.get("error") or value.get("isError") or value.get("exitCode", 0) != 0
                )
                result = {"state": "failed" if failed else "succeeded", "result": value}
            except (DomainError, OSError, TimeoutError, httpx.HTTPError) as exc:
                result = {
                    "state": "failed"
                    if isinstance(exc, DomainError)
                    and exc.code
                    not in {
                        "TOOL_OUTCOME_UNKNOWN",
                        "MCP_OUTCOME_UNKNOWN",
                        "ACTIVE_TASK_CONTEXT_REQUIRED",
                        "CONTEXT_SOURCE_FORGOTTEN",
                        "TASK_BUDGET_EXCEEDED",
                    }
                    else "unknown",
                    "result": {
                        "error": exc.code
                        if isinstance(exc, DomainError)
                        else "TOOL_OUTCOME_UNKNOWN"
                    },
                }
            except asyncio.CancelledError:
                result = {"state": "unknown", "result": {"error": "TOOL_OUTCOME_UNKNOWN"}}
            finally:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                self.active.discard(operation)
        result["requestId"] = payload["requestId"]
        result["finishedMs"] = now_ms()

        def finish(db):
            event(
                db,
                task["origin_conversation_id"],
                "capability.completed",
                result,
                key=key + ":result",
                task_id=task["id"],
            )
            activity_event(
                db,
                task["origin_conversation_id"],
                "task.activity",
                {"taskId": task["id"], "activityId": key},
                task_id=task["id"],
            )

        await self.db.call(finish, write=True)
        self.runtime.wakeup.set()
        return result

    async def close(self):
        self.closed = True
        running = list(self.requests)
        for operation in running:
            operation.cancel()
        await asyncio.gather(*running, return_exceptions=True)
