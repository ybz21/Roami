"""Durable write-ahead post facts; release admission is a required host dependency."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_repository import receipt


class PostJournal:
    def __init__(self, database, admit=None):
        self.db, self.admit = database, admit

    def authority(self, db, binding, release_id):
        if self.admit is None:
            raise DomainError("PUBLICATION_RELEASE_ADMISSION_UNAVAILABLE", 409)
        value = self.admit(db, binding, release_id)
        if value.get("owner") != binding["owner"]:
            raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
        return value

    async def reserve(self, binding, release_id):
        def write(db):
            context = self.authority(db, binding, release_id)
            business = {k: context[k] for k in ("projectId", "channel", "accountId", "businessKey")}
            digest = hashlib.sha256(encoded(business).encode()).hexdigest()
            root = receipt(
                db,
                binding["owner"],
                "publication-root:" + digest,
                {**business, "itemId": context["itemId"], "swarmId": context["swarmId"]},
                lambda: {"rootId": identity(), "kind": "publication_root", **business},
                swarm_id=context["swarmId"],
            )
            context = {**context, "rootId": root["rootId"]}
            attempt = receipt(
                db,
                binding["owner"],
                "publication-attempt:" + root["rootId"],
                context,
                lambda: {
                    "attemptId": identity(),
                    "kind": "publication_attempt",
                    "context": context,
                },
                swarm_id=context["swarmId"],
            )
            return attempt

        return await self.db.call(write, write=True)

    @staticmethod
    def fact(db, owner, project_id, key):
        found = row(
            db,
            "SELECT receipt_json FROM swarm_commands WHERE owner_id=? AND scope_project_id=? AND command_key=?",
            (owner, project_id, key),
        )
        return json.loads(found["receipt_json"]) if found else None

    async def record(self, binding, attempt, event):
        expected = attempt["context"]
        if expected["owner"] != binding["owner"]:
            raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
        phase = event.get("phase")
        if phase not in {"post_submit", "post_created"}:
            raise DomainError("INVALID_PUBLICATION_JOURNAL_PHASE")
        for name in ("businessKey", "accountId", "versionSha256"):
            if event.get(name) != expected[name]:
                raise DomainError("PUBLICATION_RELEASE_SCOPE_CONFLICT", 409)

        def write(db):
            stored = self.fact(
                db,
                binding["owner"],
                expected["projectId"],
                "publication-attempt:" + expected["rootId"],
            )
            if stored != attempt:
                raise DomainError("PUBLICATION_ATTEMPT_NOT_FOUND", 404)
            key = "publication-" + phase + ":" + attempt["attemptId"]
            if phase == "post_submit":
                current = self.authority(db, binding, expected["releaseId"])
                if current != {k: v for k, v in expected.items() if k != "rootId"}:
                    raise DomainError("PUBLICATION_RELEASE_SCOPE_CONFLICT", 409)
                if self.fact(db, binding["owner"], expected["projectId"], key):
                    raise DomainError("PUBLICATION_RECONCILIATION_REQUIRED", 409)
            else:
                submitted = self.fact(
                    db,
                    binding["owner"],
                    expected["projectId"],
                    "publication-post_submit:" + attempt["attemptId"],
                )
                if not submitted or any(
                    submitted["event"].get(k) != event.get(k) for k in ("requestSha256", "media")
                ):
                    raise DomainError("PUBLICATION_SUBMISSION_RECEIPT_REQUIRED", 409)
            return receipt(
                db,
                binding["owner"],
                key,
                event,
                lambda: {
                    "kind": "publication_transport_fact",
                    "attemptId": attempt["attemptId"],
                    "event": event,
                },
                scope_project_id=expected["projectId"],
            )

        return await self.db.call(write, write=True)
