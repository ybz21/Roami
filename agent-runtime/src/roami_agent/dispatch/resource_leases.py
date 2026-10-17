"""Durable control fences; expiry never proves that an input driver stopped."""

import hashlib
import json
import re

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row


class ResourceLeases:
    def __init__(self, database, *, lease_ms=30_000):
        if (
            not isinstance(lease_ms, int)
            or isinstance(lease_ms, bool)
            or not 1 <= lease_ms <= 60_000
        ):
            raise DomainError("INVALID_RESOURCE_LEASE_CONFIG")
        self.db, self.lease_ms = database, lease_ms

    @staticmethod
    def _payload(value, limit, code):
        try:
            if not isinstance(value, dict):
                raise TypeError
            packed = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            if len(packed.encode()) > limit:
                raise ValueError
            return packed
        except (ValueError, TypeError) as exc:
            raise DomainError(code) from exc

    @staticmethod
    def _task(db, owner, task_id, run_id):
        task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
        if not task or not row(
            db,
            "SELECT id FROM task_attempts WHERE id=? AND task_id=? AND task_revision=? AND state IN ('starting','running') AND attempt_no=(SELECT MAX(attempt_no) FROM task_attempts WHERE task_id=? AND task_revision=?)",
            (run_id, task_id, task["revision"], task_id, task["revision"]),
        ):
            raise DomainError("RESOURCE_TASK_NOT_FOUND", 404)
        if (
            task["state"] not in {"preparing", "running"}
            or json.loads(task["budget_json"])["deadlineMs"] <= now_ms()
        ):
            raise DomainError("RESOURCE_TASK_INACTIVE", 409)
        return task

    @staticmethod
    def _owned(db, owner, resource_id):
        item = row(db, "SELECT * FROM resources WHERE id=? AND owner_id=?", (resource_id, owner))
        if not item:
            raise DomainError("RESOURCE_NOT_FOUND", 404)
        return item

    @staticmethod
    def _pending(db, resource_id):
        return row(
            db,
            "SELECT id FROM resource_actions WHERE resource_id=? AND (state='running' OR (state='unknown' AND COALESCE(json_extract(result_json,'$.inputStopped'),0)!=1)) LIMIT 1",
            (resource_id,),
        )

    def _guard(self, db, owner, resource_id, task_id, run_id, epoch):
        self._task(db, owner, task_id, run_id)
        item = self._owned(db, owner, resource_id)
        if (item["owner_task_id"], item["owner_run_id"], item["lease_epoch"]) != (
            task_id,
            run_id,
            epoch,
        ):
            raise DomainError("RESOURCE_LEASE_STALE", 409)
        if item["state"] != "held":
            raise DomainError("RESOURCE_INPUT_PAUSED", 409)
        self._input_admitted(db, task_id)
        if (item["lease_until_ms"] or 0) <= now_ms():
            raise DomainError("RESOURCE_LEASE_EXPIRED", 409)
        return item

    @staticmethod
    def _input_admitted(db, task_id):
        if row(
            db,
            "SELECT id FROM resources WHERE owner_task_id=? AND state IN ('paused','pausing','quarantined') LIMIT 1",
            (task_id,),
        ):
            raise DomainError("RESOURCE_INPUT_PAUSED", 409)

    async def claim(self, owner, task_id, run_id, kind, resource_key, *, created=False):
        if (
            kind not in {"browser", "desktop"}
            or not isinstance(resource_key, str)
            or not 1 <= len(resource_key) <= 500
        ):
            raise DomainError("INVALID_RESOURCE")

        def write(db):
            task = self._task(db, owner, task_id, run_id)
            self._input_admitted(db, task_id)
            db.execute(
                "INSERT OR IGNORE INTO resources(id,node_id,kind,resource_key) VALUES(?,'local',?,?)",
                (identity(), kind, resource_key),
            )
            item = row(
                db,
                "SELECT * FROM resources WHERE node_id='local' AND kind=? AND resource_key=?",
                (kind, resource_key),
            )
            same_holder = item["state"] == "held" and (
                item["owner_id"],
                item["owner_task_id"],
                item["owner_run_id"],
            ) == (owner, task_id, run_id)
            if same_holder:
                if self._pending(db, item["id"]):
                    raise DomainError("RESOURCE_ACTION_PENDING", 409)
            elif item["state"] != "idle" or item["owner_task_id"]:
                raise DomainError("RESOURCE_BUSY", 409)
            epoch = item["lease_epoch"] + 1
            deadline = min(now_ms() + self.lease_ms, json.loads(task["budget_json"])["deadlineMs"])
            db.execute(
                "UPDATE resources SET owner_id=?,owner_task_id=?,owner_run_id=?,state='held',lease_epoch=?,lease_until_ms=?,created_by_task=? WHERE id=?",
                (
                    owner,
                    task_id,
                    run_id,
                    epoch,
                    deadline,
                    int(created or (same_holder and item["created_by_task"])),
                    item["id"],
                ),
            )
            return row(db, "SELECT * FROM resources WHERE id=?", (item["id"],))

        return await self.db.call(write, write=True)

    async def observe(self, owner, resource_id, task_id, run_id, epoch, signature, body):
        packed = self._payload(body, 64_000, "INVALID_RESOURCE_OBSERVATION")
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise DomainError("INVALID_RESOURCE_OBSERVATION")

        def write(db):
            item = self._guard(db, owner, resource_id, task_id, run_id, epoch)
            if self._pending(db, resource_id):
                raise DomainError("RESOURCE_ACTION_PENDING", 409)
            previous = row(
                db,
                "SELECT * FROM resource_observations WHERE resource_id=? ORDER BY rowid DESC LIMIT 1",
                (resource_id,),
            )
            scene = item["scene_epoch"] + int(not previous or previous["signature"] != signature)
            oid = identity()
            db.execute(
                "INSERT INTO resource_observations VALUES(?,?,?,?,?,?,?,?,?)",
                (oid, resource_id, task_id, run_id, epoch, scene, signature, packed, now_ms()),
            )
            db.execute("UPDATE resources SET scene_epoch=? WHERE id=?", (scene, resource_id))
            return {
                **body,
                "id": oid,
                "resourceId": resource_id,
                "sceneEpoch": scene,
                "signature": signature,
            }

        return await self.db.call(write, write=True)

    async def begin(
        self, owner, resource_id, task_id, run_id, epoch, observation_id, scene_epoch, action, key
    ):
        packed = self._payload(action, 16_000, "INVALID_RESOURCE_ACTION")
        digest = hashlib.sha256(
            encoded(
                [resource_id, task_id, run_id, epoch, observation_id, scene_epoch, action]
            ).encode()
        ).hexdigest()
        if not isinstance(key, str) or not 1 <= len(key) <= 300 or len(packed.encode()) > 16_000:
            raise DomainError("INVALID_RESOURCE_ACTION")

        def write(db):
            existing = row(db, "SELECT * FROM resource_actions WHERE idempotency_key=?", (key,))
            if existing:
                if existing["payload_sha256"] != digest or not self._owned(
                    db, owner, existing["resource_id"]
                ):
                    raise DomainError("RESOURCE_ACTION_CONFLICT", 409)
                return {**existing, "dispatch": False}
            item = self._guard(db, owner, resource_id, task_id, run_id, epoch)
            if self._pending(db, resource_id):
                raise DomainError("RESOURCE_ACTION_PENDING", 409)
            observed = row(
                db,
                "SELECT * FROM resource_observations WHERE resource_id=? ORDER BY rowid DESC LIMIT 1",
                (resource_id,),
            )
            if (
                not observed
                or (observed["id"], observed["lease_epoch"], observed["scene_epoch"])
                != (observation_id, epoch, scene_epoch)
                or item["scene_epoch"] != scene_epoch
            ):
                raise DomainError("RESOURCE_SCENE_CHANGED", 409)
            aid = identity()
            db.execute(
                "INSERT INTO resource_actions(id,resource_id,task_id,run_id,lease_epoch,observation_id,idempotency_key,payload_sha256,action_json,state,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,?,?,'running',?,?)",
                (
                    aid,
                    resource_id,
                    task_id,
                    run_id,
                    epoch,
                    observation_id,
                    key,
                    digest,
                    packed,
                    now_ms(),
                    now_ms(),
                ),
            )
            return {
                **row(db, "SELECT * FROM resource_actions WHERE id=?", (aid,)),
                "dispatch": True,
            }

        return await self.db.call(write, write=True)

    async def finish(self, owner, action_id, state, result):
        if state not in {"succeeded", "failed", "unknown"}:
            raise DomainError("INVALID_RESOURCE_ACTION_RESULT")
        packed = self._payload(result, 64_000, "INVALID_RESOURCE_ACTION_RESULT")
        if ("inputStopped" in result and not isinstance(result["inputStopped"], bool)) or (
            state in {"succeeded", "failed"} and result.get("inputStopped") is not True
        ):
            raise DomainError("INVALID_RESOURCE_ACTION_RESULT")

        def write(db):
            action = row(db, "SELECT * FROM resource_actions WHERE id=?", (action_id,))
            if not action:
                raise DomainError("RESOURCE_ACTION_NOT_FOUND", 404)
            item = self._owned(db, owner, action["resource_id"])
            if action["state"] == state and action["result_json"] == packed:
                return action
            if action["state"] in {"succeeded", "failed"}:
                if action["state"] != state or action["result_json"] != packed:
                    raise DomainError("RESOURCE_ACTION_CONFLICT", 409)
                return action
            db.execute(
                "UPDATE resource_actions SET state=?,result_json=?,updated_ms=? WHERE id=?",
                (state, packed, now_ms(), action_id),
            )
            if item["lease_epoch"] == action["lease_epoch"]:
                if item["state"] in {"pausing", "paused"}:
                    control = "paused" if result.get("inputStopped") is True else "pausing"
                else:
                    control = "quarantined" if state == "unknown" else item["state"]
                db.execute(
                    "UPDATE resources SET state=?,scene_epoch=scene_epoch+1 WHERE id=?",
                    (control, item["id"]),
                )
            return row(db, "SELECT * FROM resource_actions WHERE id=?", (action_id,))

        return await self.db.call(write, write=True)

    async def pause(self, owner, resource_id):
        def write(db):
            self._owned(db, owner, resource_id)
            state = "pausing" if self._pending(db, resource_id) else "paused"
            db.execute("UPDATE resources SET state=? WHERE id=?", (state, resource_id))
            return {"id": resource_id, "state": state}

        return await self.db.call(write, write=True)

    async def release(self, owner, resource_id, task_id, run_id, epoch):
        def write(db):
            item = self._owned(db, owner, resource_id)
            if (item["owner_task_id"], item["owner_run_id"], item["lease_epoch"]) != (
                task_id,
                run_id,
                epoch,
            ):
                raise DomainError("RESOURCE_LEASE_STALE", 409)
            if self._pending(db, resource_id):
                raise DomainError("RESOURCE_STOP_UNCONFIRMED", 409)
            state = "paused" if item["state"] in {"paused", "pausing"} else "idle"
            # Retain the paused task binding so it cannot acquire a replacement resource.
            db.execute(
                "UPDATE resources SET state=?,owner_task_id=CASE WHEN ?='paused' THEN owner_task_id ELSE NULL END,owner_run_id=CASE WHEN ?='paused' THEN owner_run_id ELSE NULL END,lease_until_ms=NULL,lease_epoch=lease_epoch+1 WHERE id=?",
                (state, state, state, resource_id),
            )
            return {"id": resource_id, "state": state}

        return await self.db.call(write, write=True)

    async def resume(self, owner, resource_id):
        def write(db):
            item = self._owned(db, owner, resource_id)
            if (
                item["state"] != "paused"
                or item["lease_until_ms"] is not None
                or self._pending(db, resource_id)
            ):
                raise DomainError("RESOURCE_STOP_UNCONFIRMED", 409)
            db.execute(
                "UPDATE resources SET state='idle',owner_task_id=NULL,owner_run_id=NULL,lease_epoch=lease_epoch+1 WHERE id=?",
                (resource_id,),
            )
            return {"id": resource_id, "state": "idle"}

        return await self.db.call(write, write=True)

    async def recover(self):
        def write(db):
            db.execute(
                "UPDATE resource_actions SET state='unknown',updated_ms=? WHERE state='running'",
                (now_ms(),),
            )
            db.execute(
                "UPDATE resources SET state='quarantined',lease_until_ms=NULL WHERE owner_task_id IS NOT NULL AND state NOT IN ('paused','pausing')"
            )

        await self.db.call(write, write=True)

    async def scope(self, binding, *, input_action=False):
        owner, task_id, turn_id = binding["owner"], binding.get("taskId"), binding.get("turnId")
        run_id = binding.get("runId")
        if not task_id or not turn_id or not run_id:
            raise DomainError("RESOURCE_TASK_REQUIRED", 409)

        def read(db):
            attempt = row(
                db,
                "SELECT a.id FROM task_attempts a JOIN turns t ON t.branch_id=a.native_branch_id "
                "JOIN tasks k ON k.id=a.task_id WHERE t.id=? AND t.state='running' AND a.task_id=? AND k.owner_id=? "
                "AND a.task_revision=k.revision AND a.id=? ORDER BY a.attempt_no DESC LIMIT 1",
                (turn_id, task_id, owner, run_id),
            )
            if not attempt:
                raise DomainError("RESOURCE_TASK_NOT_FOUND", 404)
            self._task(db, owner, task_id, attempt["id"])
            if input_action:
                self._input_admitted(db, task_id)
            return {"owner": owner, "taskId": task_id, "runId": attempt["id"]}

        return await self.db.call(read)

    async def resource(self, scope, resource_id):
        def read(db):
            item = self._owned(db, scope["owner"], resource_id)
            if (item["owner_task_id"], item["owner_run_id"]) != (scope["taskId"], scope["runId"]):
                raise DomainError("RESOURCE_LEASE_STALE", 409)
            return item

        return await self.db.call(read)

    async def owned(self, scope):
        return await self.db.call(
            lambda db: [
                dict(item)
                for item in db.execute(
                    "SELECT * FROM resources WHERE owner_id=? AND owner_task_id=? AND owner_run_id=?",
                    (scope["owner"], scope["taskId"], scope["runId"]),
                ).fetchall()
            ]
        )

    async def observation(self, scope, observation_id):
        def read(db):
            item = row(
                db,
                "SELECT o.* FROM resource_observations o JOIN resources r ON r.id=o.resource_id "
                "WHERE o.id=? AND r.owner_id=? AND o.task_id=? AND o.run_id=?",
                (observation_id, scope["owner"], scope["taskId"], scope["runId"]),
            )
            if not item:
                raise DomainError("RESOURCE_OBSERVATION_NOT_FOUND", 404)
            return item

        return await self.db.call(read)

    async def release_task(self, owner, task_id, run_id):
        def write(db):
            resources = db.execute(
                "SELECT * FROM resources WHERE owner_id=? AND owner_task_id=? AND owner_run_id=?",
                (owner, task_id, run_id),
            ).fetchall()
            for item in resources:
                if self._pending(db, item["id"]):
                    if item["state"] not in {"pausing", "paused"}:
                        db.execute(
                            "UPDATE resources SET state='quarantined' WHERE id=?", (item["id"],)
                        )
                    continue
                if item["state"] == "paused" and item["lease_until_ms"] is None:
                    continue
                state = "paused" if item["state"] in {"paused", "pausing"} else "idle"
                db.execute(
                    "UPDATE resources SET state=?,owner_task_id=CASE WHEN ?='paused' THEN owner_task_id ELSE NULL END,owner_run_id=CASE WHEN ?='paused' THEN owner_run_id ELSE NULL END,lease_until_ms=NULL,lease_epoch=lease_epoch+1 WHERE id=?",
                    (state, state, state, item["id"]),
                )

        await self.db.call(write, write=True)
