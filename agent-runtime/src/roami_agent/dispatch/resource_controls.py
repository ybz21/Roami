"""Owner-facing takeover waits for confirmed input stop before returning control."""

import json
import re

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


class ResourceControls:
    def __init__(self, database, leases):
        self.db, self.leases = database, leases

    def _view(self, db, resource):
        pending = self.leases.pending_scope(db, resource) is not None
        released = (
            resource["lease_until_ms"] is None
            and resource["state"] in {"idle", "paused"}
            and not pending
        )
        observation = row(
            db,
            "SELECT id,task_id,body_json FROM resource_observations WHERE resource_id=? ORDER BY rowid DESC LIMIT 1",
            (resource["id"],),
        )
        browser = re.fullmatch(
            r"browser:([A-Za-z0-9_-]{1,128}):target:([A-Za-z0-9_-]{1,128})",
            resource["resource_key"],
        )
        return {
            "browserId": browser[1] if browser else None,
            "targetId": browser[2] if browser else None,
            "id": resource["id"],
            "kind": resource["kind"],
            "state": resource["state"],
            "taskId": resource["owner_task_id"],
            "runId": resource["owner_run_id"],
            "leaseEpoch": resource["lease_epoch"],
            "sceneEpoch": resource["scene_epoch"],
            "actionPending": pending,
            "controlReleased": released,
            "takeoverReady": released and resource["state"] == "paused",
            "canPause": resource["state"] in {"held", "pausing", "quarantined"},
            "canResume": released and resource["state"] == "paused",
            "observationId": observation["id"] if observation else None,
            "observationTaskId": observation["task_id"] if observation else None,
            "observation": {
                key: value[: {"url": 1200, "title": 200, "screenshotRef": 128}[key]]
                for key, value in (
                    json.loads(observation["body_json"]) if observation else {}
                ).items()
                if key in {"url", "title", "screenshotRef"} and isinstance(value, str)
            },
        }

    async def get(self, owner, resource_id):
        return await self.db.call(
            lambda db: self._view(db, self.leases._owned(db, owner, resource_id))
        )

    async def task(self, owner, task_id):
        def read(db):
            if not row(db, "SELECT id FROM tasks WHERE id=? AND owner_id=?", (task_id, owner)):
                raise DomainError("TASK_NOT_FOUND", 404)
            tree = "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id WHERE t.owner_id=?) "
            items = rows(
                db,
                tree + "SELECT r.* FROM resources r WHERE r.owner_id=? AND "
                "((SELECT o.task_id FROM resource_observations o WHERE o.resource_id=r.id ORDER BY o.rowid DESC LIMIT 1) IN (SELECT id FROM tree) OR r.owner_task_id IN (SELECT id FROM tree)) "
                "AND (r.owner_task_id IS NULL OR r.owner_task_id IN (SELECT id FROM tree)) "
                "AND NOT (r.kind='browser' AND r.resource_key GLOB 'browser:*:context') "
                "ORDER BY CASE WHEN r.owner_task_id IS NULL THEN 1 ELSE 0 END,r.rowid DESC LIMIT 51",
                (task_id, owner, owner),
            )
            actions = rows(
                db,
                tree
                + "SELECT a.id,a.resource_id AS resourceId,a.task_id AS taskId,a.run_id AS runId,a.state,"
                "a.created_ms AS createdMs,a.updated_ms AS updatedMs,"
                "json_extract(a.result_json,'$.inputStopped') AS inputStopped,"
                "json_extract(a.result_json,'$.outcomeKnown') AS outcomeKnown,"
                "json_extract(a.result_json,'$.error') AS errorCode "
                "FROM resource_actions a WHERE a.task_id IN (SELECT id FROM tree) ORDER BY a.rowid DESC LIMIT 21",
                (task_id, owner),
            )
            for action in actions:
                for field in ("inputStopped", "outcomeKnown"):
                    if action[field] is not None:
                        action[field] = bool(action[field])
            return {
                "taskId": task_id,
                "resources": [self._view(db, item) for item in items[:50]],
                "resourcesTruncated": len(items) > 50,
                "actions": actions[:20],
                "actionsTruncated": len(actions) > 20,
            }

        return await self.db.call(read)

    async def release_ready(self, owner=None):
        def write(db):
            paused = rows(
                db,
                "SELECT * FROM resources WHERE state IN ('pausing','paused') "
                "AND (lease_until_ms IS NOT NULL OR state='pausing')"
                + (" AND owner_id=?" if owner else "")
                + " ORDER BY rowid LIMIT 32",
                (owner,) if owner else (),
            )
            for resource in paused:
                if self.leases.pending_scope(db, resource):
                    continue
                db.execute(
                    "UPDATE resources SET state='paused',lease_until_ms=NULL,lease_epoch=lease_epoch+1 WHERE id=?",
                    (resource["id"],),
                )

        await self.db.call(write, write=True)

    async def pause(self, owner, resource_id):
        await self.leases.pause(owner, resource_id)
        await self.release_ready(owner)
        return await self.get(owner, resource_id)

    async def resume(self, owner, resource_id):
        await self.leases.resume(owner, resource_id)
        return await self.get(owner, resource_id)
