"""Conversation choices are durable; only Go admits their routes and costs."""

import os

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.factory import configured_provider
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import owned


class ModelSelections:
    def __init__(self, database, settings):
        self.db, self.settings = database, settings

    async def validate(self, model, free_only=False, role="main"):
        if model is None and not free_only:
            return None
        model = model or "auto"
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise DomainError("INVALID_TASK_MODEL")
        if type(free_only) is not bool:
            raise DomainError("INVALID_TASK_MODEL")
        socket = self.settings.model_gateway_socket or os.environ.get("ROAMI_MODEL_GATEWAY_SOCKET")
        if not socket:
            raise DomainError("MODEL_GATEWAY_REQUIRED", 503)
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=socket), timeout=10
            ) as client:
                response = await client.get(
                    "http://localhost/v1/model-gateway/models/selection",
                    params={"role": role, "model": model, "freeOnly": str(free_only).lower()},
                )
        except httpx.HTTPError as exc:
            raise DomainError("MODEL_GATEWAY_UNAVAILABLE", 503) from exc
        if response.status_code != 200:
            try:
                code = response.json()["error"]["code"]
            except (KeyError, ValueError):
                code = "MODEL_GATEWAY_UNAVAILABLE"
            raise DomainError(code, response.status_code)
        return response.json()["data"]

    @staticmethod
    def save(db, cid, model, free_only=False):
        if model is not None or free_only:
            db.execute(
                "INSERT INTO conversation_models(conversation_id,model,free_only) VALUES(?,?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET model=excluded.model,free_only=excluded.free_only",
                (cid, model or "auto", int(free_only)),
            )

    async def provider(self, turn, role):
        choice = await self.db.call(
            lambda db: row(
                db,
                "SELECT model,free_only FROM conversation_models WHERE conversation_id=?",
                (turn["conversation_id"],),
            )
        )
        if not choice:
            return None
        resolved = await self.validate(choice["model"], bool(choice["free_only"]), role)
        return configured_provider(self.settings, role, selection=resolved)

    async def get(self, owner, cid):
        def read(db):
            owned(db, owner, cid)
            choice = row(
                db,
                "SELECT model,free_only FROM conversation_models WHERE conversation_id=?",
                (cid,),
            )
            return {
                "model": choice["model"] if choice else "auto",
                "freeOnly": bool(choice and choice["free_only"]),
            }

        return await self.db.call(read)

    async def update(self, owner, cid, model, free_only):
        role = await self.db.call(
            lambda db: (
                "worker"
                if row(
                    db,
                    "SELECT id FROM native_sessions WHERE conversation_id=?",
                    (owned(db, owner, cid)["id"],),
                )
                else "main"
            )
        )
        if model != "auto" or free_only:
            await self.validate(model, free_only, role)

        def write(db):
            owned(db, owner, cid)
            if row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND state IN ('pending','running')",
                (cid,),
            ) or row(
                db,
                "SELECT t.id FROM native_sessions n JOIN tasks t ON t.id=n.task_id WHERE n.conversation_id=? AND t.state IN ('queued','preparing','running','verifying','cancelling')",
                (cid,),
            ):
                raise DomainError("MODEL_CONFIGURATION_BUSY", 409)
            if model == "auto" and not free_only:
                db.execute("DELETE FROM conversation_models WHERE conversation_id=?", (cid,))
            else:
                self.save(db, cid, model, free_only)
            return {"model": model, "freeOnly": free_only}

        return await self.db.call(write, write=True)
