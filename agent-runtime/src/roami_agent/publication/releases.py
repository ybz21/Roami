"""Immutable content handoff; execution still needs current host resource admission."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.approved_assets import approved_assets
from roami_agent.publication.automatic_mode import AutomaticModeReview, current_mode_proof
from roami_agent.publication.publisher_identity import publisher_identity
from roami_agent.storage.database import row
from roami_agent.storage.publication_versions import current_goal
from roami_agent.storage.swarm_repository import receipt


class PublicationReleases:
    def __init__(self, database, artifacts, reviewer):
        self.db, self.artifacts, self.reviewer = database, artifacts, reviewer

    async def prepare(self, binding, scope, version_id, review_id, channel, account):
        mode = await AutomaticModeReview(self.db, self.reviewer).inspect(
            binding, scope, channel, account
        )

        def inspect(db):
            current_goal(db, binding, scope)
            proof = current_mode_proof(db, binding["owner"], scope, channel, account)
            if proof != mode:
                raise DomainError("PUBLICATION_POLICY_SOURCE_CHANGED", 409)
            assets = approved_assets(
                db, binding["owner"], scope, version_id, review_id, channel, account
            )
            if assets["manifest"]["author"]["taskId"] != scope["taskId"]:
                raise DomainError("PUBLICATION_VERSION_SCOPE_CONFLICT", 403)
            return assets

        assets = await self.db.call(inspect)
        for artifact in assets["manifest"]["artifacts"]:
            await self.artifacts.verified_path(binding["owner"], artifact["id"])
        payload = {
            "scope": {
                key: scope[key]
                for key in ("projectId", "swarmId", "delegationId", "memberId", "taskId")
            },
            "versionId": version_id,
            "reviewId": review_id,
            "channel": channel,
            "accountId": account,
            "manifestSha256": assets["manifestSha256"],
            "modeProofId": mode["modeProofId"],
            "sourceFingerprint": mode["sourceFingerprint"],
            "businessKey": assets["businessKey"],
            "itemId": assets["itemId"],
        }
        digest = hashlib.sha256(encoded(payload).encode()).hexdigest()

        def save(db):
            if inspect(db) != assets:
                raise DomainError("PUBLICATION_RELEASE_SOURCE_CHANGED", 409)
            return receipt(
                db,
                binding["owner"],
                "publication-release:" + digest,
                payload,
                lambda: {
                    "kind": "publication_release",
                    "releaseId": digest,
                    **payload,
                    "publicationAuthorized": False,
                },
                swarm_id=scope["swarmId"],
            )

        return await self.db.call(save, write=True)

    @staticmethod
    def read(db, owner, project_id, release_id):
        if (
            not isinstance(release_id, str)
            or len(release_id) != 64
            or any(char not in "0123456789abcdef" for char in release_id)
        ):
            raise DomainError("INVALID_PUBLICATION_RELEASE")
        stored = row(
            db,
            "SELECT receipt_json FROM swarm_commands WHERE owner_id=? "
            "AND scope_project_id=? AND command_key=?",
            (owner, project_id, "publication-release:" + release_id),
        )
        if not stored:
            raise DomainError("PUBLICATION_RELEASE_NOT_FOUND", 404)
        value = json.loads(stored["receipt_json"])
        payload = {
            key: item
            for key, item in value.items()
            if key not in {"kind", "releaseId", "publicationAuthorized"}
        }
        if (
            value.get("kind") != "publication_release"
            or value.get("releaseId") != release_id
            or value.get("scope", {}).get("projectId") != project_id
            or hashlib.sha256(encoded(payload).encode()).hexdigest() != release_id
        ):
            raise DomainError("PUBLICATION_RELEASE_INTEGRITY_FAILED", 409)
        return value

    @classmethod
    def admit(cls, db, binding, project_id, release_id, resource_admission=None):
        if binding.get("role") != "worker":
            raise DomainError("PUBLICATION_ORIGINAL_WORKER_REQUIRED", 403)
        release = cls.read(db, binding["owner"], project_id, release_id)
        scope = release["scope"]
        task = row(
            db,
            "SELECT * FROM tasks WHERE id=? AND owner_id=?",
            (binding.get("taskId"), binding["owner"]),
        )
        run = row(
            db,
            "SELECT * FROM task_attempts WHERE id=? AND task_id=?",
            (binding.get("runId"), binding.get("taskId")),
        )
        if not task or not run or task["id"] != scope["taskId"]:
            raise DomainError("PUBLICATION_PUBLISHER_NOT_CURRENT", 409)
        operation = json.loads(task["intent_json"]).get("coordinationAuthorization") or {}
        execution = publisher_identity(
            db,
            binding["owner"],
            {
                **scope,
                "operationId": operation.get("operationId"),
                "steerSourceRevision": operation.get("sourceTaskRevision"),
                "steerSourceRunId": operation.get("sourceRunId"),
            },
            {"taskId": task["id"], "revision": run["task_revision"], "runId": run["id"]},
        )
        mode = current_mode_proof(
            db, binding["owner"], scope, release["channel"], release["accountId"]
        )
        if any(mode.get(key) != release[key] for key in ("modeProofId", "sourceFingerprint")):
            raise DomainError("PUBLICATION_POLICY_SOURCE_CHANGED", 409)
        assets = approved_assets(
            db,
            binding["owner"],
            scope,
            release["versionId"],
            release["reviewId"],
            release["channel"],
            release["accountId"],
        )
        if assets["manifestSha256"] != release["manifestSha256"]:
            raise DomainError("PUBLICATION_RELEASE_SOURCE_CHANGED", 409)
        if resource_admission is None:
            raise DomainError("PUBLICATION_RESOURCE_ADMISSION_UNAVAILABLE", 409)
        route = resource_admission(db, binding, release, execution)
        expected = {
            **execution,
            "channel": release["channel"],
            "accountId": release["accountId"],
        }
        if (
            not isinstance(route, dict)
            or any(route.get(key) != value for key, value in expected.items())
            or any(
                not isinstance(route.get(key), str) or not route[key]
                for key in ("resourceId", "routeId", "routeProofId")
            )
        ):
            raise DomainError("PUBLICATION_RESOURCE_SCOPE_CONFLICT", 403)
        return {
            "owner": binding["owner"],
            "releaseId": release_id,
            "swarmId": scope["swarmId"],
            **expected,
            "businessKey": release["businessKey"],
            "itemId": release["itemId"],
            "versionId": release["versionId"],
            "reviewId": release["reviewId"],
            "versionSha256": release["manifestSha256"],
            **{key: route[key] for key in ("resourceId", "routeId", "routeProofId")},
        }
