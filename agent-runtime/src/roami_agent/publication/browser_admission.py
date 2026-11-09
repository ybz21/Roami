"""Bind a host account probe to the original run's current browser observation."""

import hashlib
import json
import re
from urllib.parse import urlsplit

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row

HOSTS = {
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
    "bilibili": {"www.bilibili.com", "member.bilibili.com"},
}


class BrowserPublicationAdmission:
    def __init__(self, leases, resource_id, route_id, skill_sha256, account_admission=None):
        if not re.fullmatch(r"[a-f0-9]{64}", skill_sha256) or not route_id:
            raise DomainError("INVALID_PUBLICATION_ROUTE")
        self.leases, self.resource_id = leases, resource_id
        self.route_id, self.skill_sha256 = route_id, skill_sha256
        self.account_admission = account_admission

    def __call__(self, db, binding, release, execution):
        resource = self.leases._owned(db, binding["owner"], self.resource_id)
        resource = self.leases._guard(
            db,
            binding["owner"],
            resource["id"],
            execution["taskId"],
            execution["runId"],
            resource["lease_epoch"],
        )
        if resource["kind"] != "browser":
            raise DomainError("PUBLICATION_RESOURCE_SCOPE_CONFLICT", 403)
        if self.leases.pending_scope(db, resource):
            raise DomainError("RESOURCE_ACTION_PENDING", 409)
        observed = row(
            db,
            "SELECT * FROM resource_observations WHERE resource_id=? ORDER BY rowid DESC LIMIT 1",
            (resource["id"],),
        )
        if not observed or any(
            observed[key] != expected
            for key, expected in {
                "task_id": execution["taskId"],
                "run_id": execution["runId"],
                "lease_epoch": resource["lease_epoch"],
                "scene_epoch": resource["scene_epoch"],
            }.items()
        ):
            raise DomainError("RESOURCE_SCENE_CHANGED", 409)
        try:
            url = urlsplit(json.loads(observed["body_json"]).get("url", ""))
            allowed = (
                url.scheme == "https"
                and not url.username
                and not url.password
                and url.port in (None, 443)
                and url.hostname in HOSTS.get(release["channel"], set())
            )
        except (ValueError, TypeError):
            allowed = False
        if not allowed:
            raise DomainError("PUBLICATION_PLATFORM_RESOURCE_REQUIRED", 403)
        if self.account_admission is None:
            raise DomainError("PUBLICATION_ACCOUNT_PROBE_UNAVAILABLE", 409)
        account = self.account_admission(db, binding, release, resource, observed)
        expected = {
            "resourceId": resource["id"],
            "observationId": observed["id"],
            "channel": release["channel"],
            "accountId": release["accountId"],
            "leaseEpoch": resource["lease_epoch"],
            "sceneEpoch": resource["scene_epoch"],
            "signature": observed["signature"],
        }
        if (
            not isinstance(account, dict)
            or any(account.get(key) != value for key, value in expected.items())
            or account.get("kind") != "publication_account_identity"
            or not isinstance(account.get("proofId"), str)
            or not account["proofId"]
        ):
            raise DomainError("PUBLICATION_ACCOUNT_SCOPE_CONFLICT", 403)
        payload = {
            **execution,
            **expected,
            "routeId": self.route_id,
            "skillSha256": self.skill_sha256,
            "accountProofId": account["proofId"],
        }
        return {
            **execution,
            "channel": release["channel"],
            "accountId": release["accountId"],
            "resourceId": resource["id"],
            "routeId": self.route_id,
            "routeProofId": hashlib.sha256(encoded(payload).encode()).hexdigest(),
        }
