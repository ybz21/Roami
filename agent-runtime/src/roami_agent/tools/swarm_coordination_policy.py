"""Resolve a coordinated Main's scope from its host ledger before tool effects."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_agent.storage.swarm_coordination_admission import for_turn
from roami_agent.storage.swarm_evidence import evidence
from roami_agent.tools.swarm_coordination_artifacts import current_tool_artifact
from roami_agent.tools.swarm_coordination_catalog import (
    COORDINATION_OPERATIONS,
    SWARM_READS,
    SWARM_WRITES,
)
from roami_agent.tools.swarm_coordination_writes import project_write


class SwarmCoordinationPolicy:
    def __init__(self, database, targets):
        self.db, self.targets = database, targets

    async def tool_names(self, turn, role):
        if role != "main":
            return None

        def read(db):
            if for_turn(db, turn) is None:
                return None
            assert_context_admitted(db, turn)
            return COORDINATION_OPERATIONS

        return await self.db.call(read)

    @staticmethod
    def steer_arguments(db, value, task, args):
        previous = row(
            db,
            "SELECT payload_json FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND json_extract(payload_json,'$.coordinationAuthorization.batchId')=? ORDER BY rowid LIMIT 1",
            (task["id"], value["id"]),
        )
        if previous:
            payload = json.loads(previous["payload_json"])
            if payload["text"] != args["text"] or payload.get("sourceQuote") != args.get(
                "sourceQuote"
            ):
                raise DomainError("TASK_STEER_KEY_CONFLICT", 409)
            return {**args, "revision": payload["expectedRevision"], "requestComplete": False}
        attempt = row(
            db,
            "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"], task["revision"]),
        )
        read = row(
            db,
            "SELECT m.content_json FROM tool_calls x JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? AND x.tool_name='task_status' AND x.state='succeeded' AND json_extract(x.arguments_json,'$.taskId')=? ORDER BY x.rowid DESC LIMIT 1",
            (value["turn_id"], task["id"]),
        )
        result = None
        if read:
            try:
                items = json.loads(json.loads(read["content_json"]).get("text", "null"))
                result = (
                    next(
                        (
                            item
                            for item in items
                            if isinstance(item, dict) and item.get("id") == task["id"]
                        ),
                        None,
                    )
                    if isinstance(items, list)
                    else None
                )
            except (ValueError, TypeError):
                pass
        if (
            not result
            or not attempt
            or result.get("revision") != task["revision"]
            or (result.get("latestAttempt") or {}).get("runId") != attempt["id"]
        ):
            raise DomainError("SWARM_COORDINATION_TASK_STATUS_REQUIRED", 409)
        if args.get("revision") not in (None, task["revision"]):
            raise DomainError("TASK_REVISION_CHANGED", 409)
        return {**args, "revision": task["revision"], "requestComplete": False}

    def context(self, db, binding):
        if not binding.get("turnId"):
            return None
        turn = row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
        if not turn:
            return None
        value = for_turn(db, {**turn, "lease_epoch": binding.get("leaseEpoch")})
        if value is None:
            return None
        if (
            binding.get("owner") != turn["owner_id"]
            or binding.get("conversation") != turn["conversation_id"]
            or binding.get("taskId")
            or binding.get("role") != "main"
            or binding.get("originMessageId") != value["delegation"]["source_message_id"]
        ):
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        return admitted_batch(db, turn["owner_id"], turn["id"], lease_epoch=binding["leaseEpoch"])

    @staticmethod
    def scope(db, value, name, args):
        delegation = value["delegation"]
        members = json.loads(delegation["member_ids_json"])
        tasks = rows(
            db,
            "SELECT t.* FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id JOIN tasks t ON t.id=w.task_id WHERE m.swarm_id=? AND m.id IN (SELECT value FROM json_each(?)) AND t.owner_id=? AND t.origin_conversation_id=?",
            (
                value["swarm_id"],
                delegation["member_ids_json"],
                value["owner_id"],
                value["conversation_id"],
            ),
        )
        by_id = {task["id"]: task for task in tasks}
        if name in SWARM_READS | SWARM_WRITES:
            if args.get("swarmId") != value["swarm_id"]:
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
            if args.get("memberId") is not None and args["memberId"] not in members:
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        elif name not in COORDINATION_OPERATIONS:
            raise DomainError("SWARM_COORDINATION_OPERATION_UNAVAILABLE", 403)
        if name in {"swarm_publication_prepare", "swarm_publication_release"} and (
            args.get("delegationId") != delegation["id"]
            or args.get("projectId") != delegation["projectId"]
        ):
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        if name in {"swarm_publication_review", "swarm_publication_media"}:
            publication = row(
                db,
                "SELECT p.delegation_id FROM swarm_publication_versions v JOIN swarm_publication_items p ON p.id=v.item_id WHERE v.id=? AND p.swarm_id=? AND p.owner_id=?",
                (args.get("versionId"), value["swarm_id"], value["owner_id"]),
            )
            if not publication or publication["delegation_id"] != delegation["id"]:
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        if name in {"task_status", "task_steer", "swarm_verify"}:
            task = by_id.get(args.get("taskId"))
            if not task:
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
            if name == "task_steer":
                args = SwarmCoordinationPolicy.steer_arguments(db, value, task, args)
            if name == "swarm_verify":
                attempt = row(
                    db,
                    "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                    (task["id"], task["revision"]),
                )
                if (
                    args.get("revision") != task["revision"]
                    or not attempt
                    or args.get("runId") != attempt["id"]
                ):
                    raise DomainError("TASK_RESULT_SUPERSEDED", 409)
        if name == "artifact_read":
            allowed = set()
            for task in tasks:
                attempt = row(
                    db,
                    "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                    (task["id"], task["revision"]),
                )
                if attempt:
                    allowed.update(item["id"] for item in evidence(db, task, attempt))
            if args.get("id") not in allowed and not current_tool_artifact(
                db, value, args.get("id")
            ):
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        if name == "swarm_project_update" and args.get("operation") not in {"record", "review"}:
            raise DomainError("SWARM_COORDINATION_OPERATION_UNAVAILABLE", 403)
        if name == "swarm_post":
            kind = args.get("kind") or "progress"
            recipient = args.get("recipientMemberId")
            if recipient is not None and recipient not in members:
                raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
            if kind == "reply":
                source = next(
                    (item for item in value["inputs"] if item["postId"] == args.get("replyTo")),
                    None,
                )
                if not source or recipient not in (None, source["memberId"]):
                    raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
                args = {
                    **args,
                    "messageKey": "coordination:" + value["id"] + ":reply:" + str(source["postId"]),
                }
            elif kind in {"progress", "question"} and (kind != "question" or recipient):
                key = args.get("messageKey")
                if not isinstance(key, str) or not key.strip():
                    raise DomainError("SWARM_COORDINATION_MESSAGE_KEY_REQUIRED", 409)
                prefix = "coordination:" + value["id"] + ":message:"
                args = {
                    **args,
                    "messageKey": key
                    if key.startswith(prefix)
                    else prefix + hashlib.sha256(key.encode()).hexdigest(),
                }
            else:
                raise DomainError("SWARM_COORDINATION_OPERATION_UNAVAILABLE", 403)
        return args

    async def admit(self, tool, args, binding, *, after=False):
        value = await self.db.call(lambda db: self.context(db, binding))
        if value is None:
            return args, binding
        args = await self.db.call(lambda db: self.scope(db, value, tool.name, args))
        if tool.name == "project_okr_context":
            binding = {**binding, "coordinationProjectId": value["delegation"]["projectId"]}
        if tool.name == "file_read":
            workspace = await self.targets.project_workspace(value["delegation"]["projectId"])
            if after and binding.get("workspace") != workspace:
                raise DomainError("SWARM_COORDINATION_WORKSPACE_CHANGED", 409)
            binding = {**binding, "workspace": workspace}
            await self.db.call(lambda db: self.context(db, binding))
        return await self.db.call(
            lambda db: project_write(db, self.context(db, binding), tool.name, args, binding)
        )
