"""Private ASGI transport. The public Go gateway is the only login/auth boundary."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .conversation import owned
from .runtime import COMMANDS, Runtime
from .storage import DomainError, row


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversation(Payload):
    title: str = Field(default="New conversation", max_length=200)


class SendMessage(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


class Compact(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    focus: str = Field(default="", max_length=2000)


class ReadCursor(Payload):
    eventId: int = Field(ge=0)


class Fork(Payload):
    messageId: str


class CreateTask(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    conversationId: str
    goal: str = Field(min_length=1, max_length=20_000)
    executor: Literal["native", "codex", "claude"] = "native"
    target: dict | None = None
    fromMessageId: str | None = None
    parentTaskId: str | None = None


class Report(Payload):
    taskId: str
    runId: str
    revision: int = Field(ge=1)
    result: dict


class Proactive(Payload):
    conversationId: str
    text: str = Field(min_length=1, max_length=30_000)
    source: str = Field(min_length=1, max_length=100)
    dedupeKey: str = Field(min_length=1, max_length=200)
    priority: Literal["normal", "attention"] = "normal"


class Confirm(Payload):
    accepted: bool


class SaveMemory(Payload):
    title: str = Field(max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    sourceMessageId: str
    kind: Literal["fact", "decision", "preference", "summary"] = "fact"
    projectId: str | None = None
    conversationId: str | None = None
    taskId: str | None = None
    dayKey: str | None = None


Owner = Annotated[str, Header(alias="X-Roami-Owner", min_length=1, max_length=200)]


def create_app(runtime: Runtime, *, manage_lifecycle=True):
    @asynccontextmanager
    async def lifespan(app):
        if manage_lifecycle:
            await runtime.start()
        yield
        if manage_lifecycle:
            await runtime.close()

    app = FastAPI(
        title="Roami Agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": {"code": exc.code}}, status_code=exc.status)

    @app.get("/v1/status")
    async def status(owner: Owner):
        return {
            "data": {
                "model": runtime.model.model,
                "configured": bool(runtime.model.model),
                "commands": COMMANDS,
                "writerBacklog": runtime.db.pending,
            }
        }

    @app.get("/v1/conversations")
    async def list_conversations(owner: Owner):
        return {"data": await runtime.conversations.list(owner)}

    @app.post("/v1/conversations", status_code=201)
    async def create_conversation(body: CreateConversation, owner: Owner):
        return {"data": await runtime.conversations.create(owner, body.title)}

    @app.get("/v1/conversations/{cid}/messages")
    async def messages(cid: str, owner: Owner):
        return {"data": await runtime.conversations.messages(owner, cid)}

    @app.post("/v1/conversations/{cid}/messages", status_code=202)
    async def send(cid: str, body: SendMessage, owner: Owner):
        return {"data": await runtime.submit(owner, cid, body.requestKey, body.text)}

    @app.post("/v1/conversations/{cid}/fork")
    async def fork(cid: str, body: Fork, owner: Owner):
        return {"data": await runtime.conversations.fork(owner, cid, body.messageId)}

    @app.get("/v1/conversations/{cid}/events")
    async def events(
        cid: str,
        request: Request,
        owner: Owner,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        await runtime.conversations.get(owner, cid)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError as exc:
            raise DomainError("INVALID_EVENT_CURSOR") from exc
        if cursor < 0:
            raise DomainError("INVALID_EVENT_CURSOR")

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = await runtime.conversations.events(owner, cid, cursor)
                for item in batch:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: {item['kind']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                if batch:
                    idle = 0
                    continue
                idle += 1
                if idle >= 50:
                    yield ": ping\n\n"
                    idle = 0
                await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/conversations/{cid}/context")
    async def context(cid: str, owner: Owner):
        result = await runtime.context.project(owner, cid)
        return {"data": {k: v for k, v in result.items() if k != "messages"}}

    @app.get("/v1/conversations/{cid}/context/snapshots/{snapshot_id}")
    async def snapshot(cid: str, snapshot_id: str, owner: Owner):
        def read(db):
            owned(db, owner, cid)
            item = row(
                db,
                "SELECT s.* FROM context_snapshots s JOIN branches b ON b.id=s.branch_id "
                "WHERE s.id=? AND b.conversation_id=?",
                (snapshot_id, cid),
            )
            if not item:
                raise DomainError("SNAPSHOT_NOT_FOUND", 404)
            return dict(item, summary=json.loads(item["summary_json"]))

        return {"data": await runtime.db.call(read)}

    @app.post("/v1/conversations/{cid}/compact", status_code=202)
    async def compact(cid: str, body: Compact, owner: Owner):
        job = await runtime.context.request(owner, cid, body.requestKey, body.focus)
        runtime.wakeup.set()
        return {"data": {"operationId": job["id"], "state": job["state"]}}

    @app.get("/v1/conversations/{cid}/compactions/{job_id}")
    async def compaction(cid: str, job_id: str, owner: Owner):
        await runtime.conversations.get(owner, cid)
        job = await runtime.db.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE id=? AND kind='context.compact'", (job_id,)
            )
        )
        if not job or json.loads(job["payload_json"])["conversationId"] != cid:
            raise DomainError("COMPACTION_NOT_FOUND", 404)
        return {"data": {"operationId": job_id, **json.loads(job["payload_json"])}}

    @app.post("/v1/conversations/{cid}/compactions/{job_id}/cancel")
    async def cancel_compaction(cid: str, job_id: str, owner: Owner):
        return {"data": await runtime.context.cancel(owner, cid, job_id)}

    @app.post("/v1/conversations/{cid}/read")
    async def mark_read(cid: str, body: ReadCursor, owner: Owner):
        return {"data": await runtime.notifications.mark_read(owner, cid, body.eventId)}

    @app.get("/v1/notifications")
    async def notifications(owner: Owner):
        return {
            "data": {
                "items": await runtime.notifications.list(owner),
                "unread": await runtime.notifications.unread(owner),
            }
        }

    @app.get("/v1/tasks")
    async def tasks(owner: Owner, conversationId: str | None = None):
        return {"data": await runtime.tasks.list(owner, conversationId)}

    @app.post("/v1/tasks", status_code=202)
    async def create_task(body: CreateTask, owner: Owner):
        result = await runtime.tasks.create(
            owner,
            body.conversationId,
            body.goal,
            key=body.requestKey,
            parent_task_id=body.parentTaskId,
            executor=body.executor,
            target=body.target,
            from_message_id=body.fromMessageId,
            record_intent=True,
        )
        runtime.wakeup.set()
        return {"data": result}

    @app.post("/v1/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, owner: Owner):
        result = await runtime.tasks.cancel(owner, task_id)
        runtime.wakeup.set()
        return {"data": result}

    @app.post("/v1/tasks/{task_id}/verify")
    async def verify_task(task_id: str, body: Confirm, owner: Owner):
        return {"data": await runtime.confirm(owner, task_id, body.accepted)}

    @app.get("/v1/memories")
    async def memories(
        owner: Owner,
        query: str = Query("", max_length=1000),
        conversationId: str | None = None,
        projectId: str | None = None,
        taskId: str | None = None,
        dayKey: str | None = None,
    ):
        return {
            "data": await runtime.memory.search(
                owner,
                query,
                conversation_id=conversationId,
                project_id=projectId,
                task_id=taskId,
                day_key=dayKey,
            )
        }

    @app.get("/v1/memories/{memory_id}")
    async def get_memory(memory_id: str, owner: Owner):
        return {"data": await runtime.memory.get(owner, memory_id)}

    @app.post("/v1/memories", status_code=201)
    async def save_memory(body: SaveMemory, owner: Owner):
        return {
            "data": await runtime.memory.save(
                owner,
                body.title,
                body.body,
                body.sourceMessageId,
                kind=body.kind,
                project_id=body.projectId,
                conversation_id=body.conversationId,
                task_id=body.taskId,
                day_key=body.dayKey,
            )
        }

    @app.delete("/v1/memories/{memory_id}")
    async def forget(memory_id: str, owner: Owner):
        return {"data": await runtime.memory.forget(owner, memory_id)}

    # Go never forwards /internal/*; local callers share the OS user's private socket.
    @app.post("/internal/report")
    async def report(body: Report, owner: Owner):
        result = await runtime.tasks.report(
            owner, body.taskId, body.runId, body.revision, body.result
        )
        runtime.wakeup.set()
        return {"data": result}

    @app.post("/internal/notify")
    async def notify(body: Proactive, owner: Owner):
        return {
            "data": await runtime.notifications.publish(
                owner,
                body.conversationId,
                body.text,
                source=body.source,
                dedupe_key=body.dedupeKey,
                priority=body.priority,
            )
        }

    return app
