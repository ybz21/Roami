"""Idempotent Main model commands preserve the active conversation and turn."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import owned


async def switch_model(settings, owner, cid, request_key, name):
    settings.owner(owner)
    digest = hashlib.sha256(encoded(["model", cid, name]).encode()).hexdigest()
    database = settings.runtime.db
    async with settings.command_lock:

        def receipt(db):
            owned(db, owner, cid)
            previous = row(
                db,
                "SELECT * FROM requests WHERE owner_id=? AND request_key=?",
                (owner, request_key),
            )
            if not previous:
                return None
            if previous["payload_sha256"] != digest:
                raise DomainError("REQUEST_KEY_CONFLICT", 409)
            job = row(
                db,
                "SELECT payload_json FROM jobs WHERE kind='control.model' AND aggregate_id=?",
                (previous["id"],),
            )
            return json.loads(job["payload_json"])

        previous = await database.call(receipt)
        if previous:
            return previous
        saved = await settings.save(owner, {"main": {"model": name, "reasoningEffort": None}})
        result = {"kind": "model", "model": saved["main"]["model"]}

        def record(db):
            rid = identity()
            db.execute(
                "INSERT INTO requests(id,owner_id,request_key,payload_sha256,conversation_id,accepted_ms) VALUES(?,?,?,?,?,?)",
                (rid, owner, request_key, digest, cid, now_ms()),
            )
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'control.model',?,?,?,'done',?)",
                (identity(), rid, rid, encoded(result), now_ms()),
            )
            return result

        return await database.call(record, write=True)
