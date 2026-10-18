"Private ASGI transport. The public Go gateway is the only login/auth boundary."

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from roami_agent.conversation.attachments import MAX_UPLOAD_BYTES
from roami_agent.protocol.commands import COMMANDS
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.http import (
    Compact,
    Confirm,
    ConfirmTask,
    CreateConversation,
    CreateReminder,
    CreateTask,
    DeliveryReceipt,
    Fork,
    NotificationPreferences,
    Proactive,
    ReadCursor,
    Report,
    SaveMemory,
    SendMessage,
    SteerTask,
)

Owner = Annotated[str, Header(alias="X-Roami-Owner", min_length=1, max_length=200)]


def create_app(runtime, *, manage_lifecycle=True):
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

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(request, exc):
        return JSONResponse({"error": {"code": "INVALID_REQUEST"}}, status_code=422)

    @app.get("/v1/capabilities")
    async def capabilities(owner: Owner):
        return {"data": runtime.capability_settings.view(owner)}

    @app.put("/v1/capabilities")
    async def save_capabilities(request: Request, owner: Owner):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                raise DomainError("INVALID_CAPABILITY_CONFIG", 413)
        try:
            patch = json.loads(body)
        except ValueError:
            raise DomainError("INVALID_CAPABILITY_CONFIG") from None
        return {"data": await runtime.capability_settings.save(owner, patch)}

    @app.get("/v1/model-settings")
    async def model_settings(owner: Owner):
        return {"data": runtime.model_settings.view(owner)}

    @app.put("/v1/model-settings")
    async def save_model_settings(request: Request, owner: Owner):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32_000:
                raise DomainError("INVALID_MODEL_CONFIG", 413)
        try:
            patch = json.loads(body)
        except ValueError:
            raise DomainError("INVALID_MODEL_CONFIG") from None
        return {"data": await runtime.model_settings.save(owner, patch)}

    @app.get("/v1/models")
    async def models(owner: Owner, role: Literal["main", "worker"] = "main"):
        return {"data": await runtime.model_settings.models(owner, role)}

    @app.post("/v1/models")
    async def probe_models(request: Request, owner: Owner):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32_000:
                raise DomainError("INVALID_MODEL_CONFIG", 413)
        try:
            patch = json.loads(body)
        except ValueError:
            raise DomainError("INVALID_MODEL_CONFIG") from None
        if (
            not isinstance(patch, dict)
            or set(patch) - {"role", "configuration"}
            or patch.get("role") not in {"main", "worker"}
            or (
                patch.get("configuration") is not None
                and not isinstance(patch["configuration"], dict)
            )
        ):
            raise DomainError("INVALID_MODEL_CONFIG")
        return {
            "data": await runtime.model_settings.models(
                owner, patch["role"], patch.get("configuration")
            )
        }

    @app.get("/v1/notification-deliveries")
    async def notification_deliveries(owner: Owner):
        return {"data": await runtime.deliveries.list(owner)}

    @app.post("/internal/deliveries/claim")
    async def claim_delivery(owner: Owner):
        return {"data": await runtime.deliveries.claim(owner)}

    @app.post("/internal/deliveries/{delivery_id}/receipt")
    async def settle_delivery(delivery_id: str, body: DeliveryReceipt, owner: Owner):
        return {
            "data": await runtime.deliveries.settle(
                owner, delivery_id, body.claimToken, body.outcome
            )
        }

    @app.get("/v1/reminders")
    async def reminders(owner: Owner):
        items = await runtime.reminders.list(owner) + await runtime.briefs.reminders(owner)
        items.sort(key=lambda item: (not item["enabled"], -item["createdMs"]))
        return {"data": items}

    @app.post("/v1/reminders")
    async def create_reminder(body: CreateReminder, owner: Owner):
        if body.kind == "daily_brief":
            if body.whenMs is not None or body.afterSeconds is not None:
                raise DomainError("INVALID_BRIEF_SCHEDULE")
            item = await runtime.briefs.create(
                owner,
                body.conversationId,
                body.text,
                body.requestKey,
                daily_at=body.dailyAt,
                timezone_name=body.timezone,
            )
            return {"data": dict(item, id="brief:" + item["id"], kind="daily_brief")}
        return {
            "data": await runtime.reminders.create(
                owner,
                body.conversationId,
                body.text,
                body.requestKey,
                when_ms=body.whenMs,
                daily_at=body.dailyAt,
                timezone_name=body.timezone,
                after_seconds=body.afterSeconds,
            )
        }

    @app.delete("/v1/reminders/{reminder_id}")
    async def cancel_reminder(reminder_id: str, owner: Owner):
        if reminder_id.startswith("brief:"):
            return {"data": await runtime.briefs.cancel(owner, reminder_id[6:])}
        return {"data": await runtime.reminders.cancel(owner, reminder_id)}

    @app.get("/v1/notification-preferences")
    async def notification_preferences(owner: Owner):
        return {"data": await runtime.notification_policy.get(owner)}

    @app.put("/v1/notification-preferences")
    async def save_notification_preferences(body: NotificationPreferences, owner: Owner):
        return {"data": await runtime.notification_policy.replace(owner, body.settings)}

    @app.get("/v1/status")
    async def status(owner: Owner):
        return {
            "data": {
                "model": runtime.model.model,
                "configured": bool(runtime.model.model),
                "memoryTimezone": runtime.memory.daily.timezone,
                "commands": COMMANDS,
                "images": runtime.settings.route("main").capabilities.get("images") is True,
                "writerBacklog": runtime.db.pending,
            }
        }

    @app.get("/v1/conversations")
    async def list_conversations(owner: Owner):
        return {"data": await runtime.conversations.list(owner)}

    @app.get("/v1/artifacts")
    async def artifacts(
        owner: Owner,
        taskId: str | None = Query(default=None, max_length=200),
        messageId: str | None = Query(default=None, max_length=200),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        return {
            "data": await runtime.artifacts.list(
                owner, task_id=taskId, message_id=messageId, limit=limit
            )
        }

    @app.post("/v1/attachments", status_code=201)
    async def upload_attachment(
        request: Request,
        owner: Owner,
        filename: str = Query(min_length=1, max_length=180),
        requestKey: str = Query(min_length=1, max_length=200),
    ):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > min(MAX_UPLOAD_BYTES, runtime.artifacts.max_bytes):
                raise DomainError("ATTACHMENT_SIZE_LIMIT", 413)
            body.extend(chunk)
        return {"data": await runtime.attachments.upload(owner, filename, requestKey, bytes(body))}

    @app.delete("/v1/attachments/{aid}")
    async def remove_attachment(aid: str, owner: Owner):
        return {"data": await runtime.attachments.remove_draft(owner, aid)}

    @app.get("/v1/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, owner: Owner):
        return {"data": await runtime.artifacts.get(owner, artifact_id)}

    @app.get("/v1/artifacts/{artifact_id}/content")
    async def artifact_content(artifact_id: str, owner: Owner):
        reference, path = await runtime.artifacts.verified_path(owner, artifact_id)
        return FileResponse(
            path,
            media_type=reference["mimeType"],
            filename=reference["name"],
            content_disposition_type="attachment",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox allow-downloads; default-src 'none'",
            },
        )

    @app.delete("/v1/artifacts/{artifact_id}")
    async def delete_artifact(artifact_id: str, owner: Owner):
        return {"data": await runtime.artifacts.delete(owner, artifact_id)}

    @app.post("/v1/main-conversation")
    async def main_conversation(owner: Owner):
        return {"data": await runtime.conversations.main(owner)}

    @app.post("/v1/conversations", status_code=201)
    async def create_conversation(body: CreateConversation, owner: Owner):
        return {
            "data": await runtime.conversations.create(
                owner, body.title, request_key=body.requestKey
            )
        }

    @app.get("/v1/conversations/{cid}/messages")
    async def messages(cid: str, owner: Owner, branch: str | None = None):
        return {"data": await runtime.conversations.messages(owner, cid, branch)}

    @app.post("/v1/conversations/{cid}/messages", status_code=202)
    async def send(cid: str, body: SendMessage, owner: Owner):
        return {
            "data": await runtime.chat.submit(
                owner, cid, body.requestKey, body.text, body.attachmentIds
            )
        }

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
            yield ": connected\n\n"
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
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/conversations/{cid}/context")
    async def context(cid: str, owner: Owner):
        result = await runtime.context.project(owner, cid)
        return {
            "data": {
                "model": runtime.model.model,
                **{k: v for k, v in result.items() if k != "messages"},
            }
        }

    @app.get("/v1/conversations/{cid}/context/snapshots/{snapshot_id}")
    async def snapshot(cid: str, snapshot_id: str, owner: Owner):
        return {"data": await runtime.context.snapshot(owner, cid, snapshot_id)}

    @app.post("/v1/conversations/{cid}/compact", status_code=202)
    async def compact(cid: str, body: Compact, owner: Owner):
        job = await runtime.context.request(owner, cid, body.requestKey, body.focus)
        runtime.wakeup.set()
        return {"data": {"operationId": job["id"], "state": job["state"]}}

    @app.get("/v1/conversations/{cid}/compactions/{job_id}")
    async def compaction(cid: str, job_id: str, owner: Owner):
        return {"data": await runtime.context.compaction(owner, cid, job_id)}

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

    @app.get("/v1/tasks/{task_id}")
    async def task_detail(task_id: str, owner: Owner):
        return {"data": await runtime.tasks.get(owner, task_id)}

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

    @app.post("/v1/tasks/{task_id}/steer", status_code=202)
    async def steer_task(task_id: str, body: SteerTask, owner: Owner):
        result = await runtime.tasks.revisions.request(
            owner, task_id, body.text, body.revision, body.requestKey
        )
        runtime.wakeup.set()
        return {"data": result}

    @app.get("/v1/tasks/{task_id}/steering/{operation_id}")
    async def steering(task_id: str, operation_id: str, owner: Owner):
        return {"data": await runtime.tasks.revisions.get(owner, task_id, operation_id)}

    @app.post("/v1/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, owner: Owner):
        result = await runtime.tasks.cancel(owner, task_id)
        runtime.wakeup.set()
        return {"data": result}

    @app.get("/v1/tasks/{task_id}/resources")
    async def task_resources(task_id: str, owner: Owner):
        return {"data": await runtime.controls.task(owner, task_id)}

    @app.get("/v1/resources/{resource_id}")
    async def resource_control(resource_id: str, owner: Owner):
        return {"data": await runtime.controls.get(owner, resource_id)}

    @app.post("/v1/resources/{resource_id}/pause")
    async def pause_resource(resource_id: str, owner: Owner):
        return {"data": await runtime.controls.pause(owner, resource_id)}

    @app.post("/v1/resources/{resource_id}/resume")
    async def resume_resource(resource_id: str, owner: Owner):
        return {"data": await runtime.controls.resume(owner, resource_id)}

    @app.post("/v1/tasks/{task_id}/verify")
    async def verify_task(task_id: str, body: ConfirmTask, owner: Owner):
        return {
            "data": await runtime.dispatch.confirm(
                owner, task_id, body.accepted, revision=body.revision, run_id=body.runId
            )
        }

    @app.get("/v1/memories")
    async def memories(
        owner: Owner,
        query: str = Query("", max_length=1000),
        conversationId: str | None = None,
        projectId: str | None = None,
        taskId: str | None = None,
        dayKey: str | None = None,
        timezone: str | None = None,
        state: Literal["active", "candidate", "conflict"] = "active",
        kind: Literal["fact", "decision", "preference", "summary"] | None = None,
    ):
        if state != "active":
            return {
                "data": await runtime.memory.candidates(
                    owner,
                    conversation_id=conversationId,
                    project_id=projectId,
                    task_id=taskId,
                    day_key=dayKey,
                    timezone=timezone,
                    kind=kind,
                    query=query,
                    state=state,
                )
            }
        if dayKey:
            timezone = timezone or runtime.memory.daily.timezone
            await runtime.memory.daily.refresh(owner, dayKey, timezone)
        return {
            "data": await runtime.memory.search(
                owner,
                query,
                conversation_id=conversationId,
                project_id=projectId,
                task_id=taskId,
                day_key=dayKey,
                timezone=timezone,
                kind=kind,
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
    async def forget(memory_id: str, owner: Owner, forgetSources: bool = True):
        return {"data": await runtime.memory.forget(owner, memory_id, forget_sources=forgetSources)}

    @app.post("/v1/memories/{memory_id}/confirm")
    async def confirm_memory(memory_id: str, body: Confirm, owner: Owner):
        return {"data": await runtime.memory.confirm(owner, memory_id, body.accepted)}

    @app.get("/v1/memories/{memory_id}/sources")
    async def memory_sources(memory_id: str, owner: Owner):
        return {"data": await runtime.memory.evidence(owner, memory_id)}

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
