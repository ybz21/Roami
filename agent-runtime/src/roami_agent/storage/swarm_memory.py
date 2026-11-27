"""Durable team memory and optional workspace storage."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row
from roami_agent.storage.swarm_repository import changed, group
from roami_agent.storage.swarm_scopes import require_scope


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


async def read_memory(swarms, owner, sid):
    value = await swarms.db.call(lambda db: group(db, owner, sid))
    if swarms.memory_backend is None and json.loads(value["target_json"]).get("kind") == "project":
        try:
            require_scope(value)
        except DomainError as exc:
            return {"available": False, "errorCode": exc.code}
        return {"available": False, "errorCode": "SWARM_PROJECT_MEMORY_UNAVAILABLE"}
    if swarms.memory_backend is not None:
        result = await swarms.memory_backend.read(swarms, owner, sid)
        if result is not None:
            return result

    def read(db):
        group(db, owner, sid)
        value = row(db, "SELECT * FROM swarm_memories WHERE swarm_id=?", (sid,))
        return {
            "available": True,
            "content": value["content"] if value else "",
            "sha256": value["sha256"] if value else digest(""),
            "source": "swarm:" + sid + "/memory",
            "updatedMs": value["updated_ms"] if value else None,
            "author": value["author"] if value else None,
        }

    return await swarms.db.call(read)


async def write_memory(swarms, owner, sid, spec):
    content = spec.get("content")
    if (
        not isinstance(content, str)
        or len(content.encode()) > 64000
        or not isinstance(spec.get("expectedSha256"), str)
    ):
        raise DomainError("INVALID_SWARM_MEMORY")
    value = await swarms.db.call(lambda db: group(db, owner, sid))
    if value["archived"]:
        raise DomainError("SWARM_ARCHIVED", 409)
    if swarms.memory_backend is not None:
        result = await swarms.memory_backend.write(swarms, owner, sid, spec)
        if result is not None:
            return result

    require_scope(value)
    if (
        json.loads(value["target_json"]).get("kind") == "project"
        or spec.get("operationKey") is not None
        or spec.get("mode") is not None
    ):
        raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)

    def write(db):
        current = row(db, "SELECT sha256 FROM swarm_memories WHERE swarm_id=?", (sid,))
        if spec["expectedSha256"] != (current["sha256"] if current else digest("")):
            raise DomainError("SWARM_MEMORY_CHANGED", 409)
        db.execute(
            "INSERT INTO swarm_memories VALUES(?,?,?,?,?) ON CONFLICT(swarm_id) DO UPDATE SET content=excluded.content,sha256=excluded.sha256,updated_ms=excluded.updated_ms,author=excluded.author",
            (sid, content, digest(content), now_ms(), owner),
        )
        changed(db, group(db, owner, sid), "swarm.memory_changed")

    await swarms.db.call(write, write=True)
    return await read_memory(swarms, owner, sid)
