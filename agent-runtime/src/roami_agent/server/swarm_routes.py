"""Authenticated-host proxy endpoints for managed collaboration."""

import asyncio
from typing import Annotated, Literal

from fastapi import Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from roami_agent.protocol.http import Payload
from roami_agent.protocol.serialization import encoded

Owner = Annotated[str, Header(alias="X-Roami-Owner", min_length=1, max_length=200)]


class CreateSwarm(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=30000)
    mainConversationId: str | None = None
    target: dict | None = None


class DependencySpec(Payload):
    member: str = Field(min_length=1, max_length=80)
    revision: int = Field(default=1, ge=1)
    artifactId: str | None = None


class DeliverableSpec(Payload):
    kind: Literal["artifact", "external_action"]
    description: str = Field(min_length=1, max_length=1000)
    mimeType: str | None = Field(default=None, max_length=100)


class MemorySwarm(Payload):
    content: str = Field(max_length=64000)
    expectedSha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class WorkSpec(Payload):
    memberId: str | None = Field(
        default=None, min_length=1, max_length=200, exclude_if=lambda value: value is None
    )
    member: str = Field(min_length=1, max_length=80)
    executor: Literal["native", "codex", "claude", "opencode", "pi"]
    title: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=30000)
    acceptance: str = Field(min_length=1, max_length=8000)
    integration: bool = False
    deliverables: list[DeliverableSpec] = Field(default_factory=list, max_length=30)
    dependencies: list[DependencySpec] = Field(default_factory=list, max_length=100)


class RoleSpec(Payload):
    name: str = Field(min_length=1, max_length=80)
    executor: Literal["native", "codex", "claude", "opencode", "pi"]
    duty: str = Field(min_length=1, max_length=8000)


class RegisterMembers(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    expectedRevision: int = Field(ge=1)
    members: list[RoleSpec] = Field(min_length=1, max_length=100)


class PlanSwarm(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    expectedRevision: int = Field(ge=1)
    items: list[WorkSpec] = Field(min_length=1, max_length=100)


class DependenciesSwarm(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    expectedRevision: int = Field(ge=1)
    workId: str = Field(min_length=1)
    dependencies: list[DependencySpec] = Field(default_factory=list, max_length=100)


class ControlSwarm(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    expectedRevision: int = Field(ge=1)
    action: Literal["pause", "resume", "stop", "archive"]


class PostSwarm(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=8000)
    workId: str | None = None
    taskRevision: int | None = Field(default=None, ge=1)


class MemberPost(PostSwarm):
    taskId: str = Field(min_length=1, max_length=200)
    runId: str = Field(min_length=1, max_length=200)
    taskRevision: int = Field(ge=1)


def mount_swarm_routes(app, runtime):
    @app.get("/v1/swarms")
    async def list_swarms(owner: Owner):
        return {"data": await runtime.swarms.list(owner)}

    @app.post("/v1/swarms")
    async def create_swarm(body: CreateSwarm, owner: Owner):
        return {"data": await runtime.swarms.create(owner, body.model_dump(exclude_none=True))}

    @app.get("/v1/swarms/{sid}")
    async def swarm_snapshot(sid: str, owner: Owner):
        return {"data": await runtime.swarms.snapshot(owner, sid)}

    @app.get("/v1/swarms/{sid}/members")
    async def members(sid: str, owner: Owner):
        value = await runtime.swarms.snapshot(owner, sid, include_memory=False)
        return {"data": value["members"]}

    @app.post("/v1/swarms/{sid}/members")
    async def register_members(sid: str, body: RegisterMembers, owner: Owner):
        return {"data": await runtime.swarms.register_members(owner, sid, body.model_dump())}

    @app.get("/v1/swarms/{sid}/members/{member_id}")
    async def member(
        sid: str,
        member_id: str,
        owner: Owner,
        before: int | None = Query(None, ge=1),
        limit: int = Query(20, ge=1, le=50),
    ):
        return {
            "data": await runtime.swarms.member(owner, sid, member_id, before=before, limit=limit)
        }

    @app.post("/v1/swarms/{sid}/plan")
    async def swarm_plan(sid: str, body: PlanSwarm, owner: Owner):
        return {"data": await runtime.swarms.plan(owner, sid, body.model_dump())}

    @app.post("/v1/swarms/{sid}/dependencies")
    async def dependencies_swarm(sid: str, body: DependenciesSwarm, owner: Owner):
        return {
            "data": await runtime.swarms.dependencies(
                owner, sid, body.model_dump(exclude_none=True)
            )
        }

    @app.post("/v1/swarms/{sid}/control")
    async def swarm_control(sid: str, body: ControlSwarm, owner: Owner):
        return {"data": await runtime.swarms.control(owner, sid, body.model_dump())}

    @app.put("/v1/swarms/{sid}/memory")
    async def swarm_memory(sid: str, body: MemorySwarm, owner: Owner):
        return {"data": await runtime.swarms.memory_write(owner, sid, body.model_dump())}

    @app.post("/v1/swarms/{sid}/messages")
    async def swarm_message(sid: str, body: PostSwarm, owner: Owner):
        return {"data": await runtime.swarms.send(owner, sid, body.model_dump(exclude_none=True))}

    # Private Unix-socket CLI return channel, not mounted by the public Go proxy.
    @app.post("/v1/swarms/{sid}/member-posts")
    async def member_post(sid: str, body: MemberPost, owner: Owner):
        return {
            "data": await runtime.swarms.post(
                owner,
                sid,
                {"commandKey": body.commandKey, "text": body.text},
                binding={
                    "taskId": body.taskId,
                    "runId": body.runId,
                    "taskRevision": body.taskRevision,
                },
            )
        }

    @app.get("/v1/swarms/{sid}/events")
    async def swarm_events(
        sid: str, request: Request, owner: Owner, after: int = Query(default=0, ge=0)
    ):
        initial = await runtime.swarms.snapshot(owner, sid)

        async def stream():
            cursor = after
            with runtime.db.conversation_events.subscribe(initial["mainConversationId"]) as changed:
                value = initial
                needs_snapshot = True
                while not await request.is_disconnected():
                    if needs_snapshot:
                        changed.clear()
                        value = await runtime.swarms.snapshot(owner, sid)
                    needs_snapshot = False
                    if value["sequence"] > cursor:
                        cursor = value["sequence"]
                        yield (
                            "id: "
                            + str(cursor)
                            + "\ndata: "
                            + encoded({"id": cursor, "kind": "swarm.snapshot", "payload": value})
                            + "\n\n"
                        )
                    try:
                        await asyncio.wait_for(changed.wait(), timeout=10)
                        await asyncio.sleep(0.25)
                        needs_snapshot = True
                    except TimeoutError:
                        yield ": heartbeat\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
