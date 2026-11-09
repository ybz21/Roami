"""Main review of current Swarm artifacts through the existing task confirmation gate."""

import json

from roami_agent.protocol.errors import DomainError, TaskVerificationRecorded
from roami_agent.storage.artifact_text_coverage import text_coverage
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_evidence import evidence, requirements
from roami_agent.storage.swarm_repository import group
from roami_agent.storage.swarm_scopes import require_scope


def admission(db, args, binding):
    swarm = group(db, binding["owner"], args["swarmId"])
    require_scope(swarm)
    if (
        binding.get("role") != "main"
        or binding.get("taskId")
        or binding.get("conversation") != swarm["conversation_id"]
    ):
        raise DomainError("SWARM_MAIN_REQUIRED", 403)
    if swarm["archived"]:
        raise DomainError("SWARM_ARCHIVED", 409)
    turn = row(
        db,
        "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "WHERE t.id=? AND t.conversation_id=? AND t.state='running' "
        "AND t.branch_id=c.active_branch_id AND c.owner_id=? AND c.deleted_ms IS NULL",
        (binding.get("turnId"), swarm["conversation_id"], binding["owner"]),
    )
    if not turn:
        raise DomainError("SWARM_MAIN_REQUIRED", 403)
    assert_context_admitted(db, turn)
    task = row(
        db,
        "SELECT t.* FROM swarm_work_items w JOIN tasks t ON t.id=w.task_id "
        "WHERE w.swarm_id=? AND t.id=? AND t.owner_id=?",
        (args["swarmId"], args["taskId"], binding["owner"]),
    )
    if not task:
        raise DomainError("SWARM_TASK_NOT_FOUND", 404)
    if task["revision"] != args["revision"]:
        raise DomainError("TASK_REVISION_CHANGED", 409)
    run = row(
        db,
        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? "
        "ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], task["revision"]),
    )
    if not run or run["id"] != args["runId"]:
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    required = requirements(db, task["id"])
    if any(item["kind"] == "external_action" for item in required):
        raise DomainError("SWARM_EXTERNAL_ACTION_USER_REQUIRED", 409)
    if task["state"] != "waiting_user":
        recorded = row(
            db,
            "SELECT id,payload_json FROM events WHERE kind='swarm.verification_recorded' "
            "AND task_id=? AND conversation_id=? "
            "AND json_extract(payload_json,'$.swarmId')=? "
            "AND json_extract(payload_json,'$.taskId')=? "
            "AND json_extract(payload_json,'$.revision')=? "
            "AND json_extract(payload_json,'$.runId')=? "
            "AND json_extract(payload_json,'$.reviewer')='main' "
            "AND json_extract(payload_json,'$.mainConversationId')=conversation_id "
            "AND json_extract(payload_json,'$.mainTurnId')=turn_id ORDER BY id DESC LIMIT 1",
            (
                task["id"],
                binding["conversation"],
                args["swarmId"],
                task["id"],
                task["revision"],
                run["id"],
            ),
        )
        fact = json.loads(recorded["payload_json"]) if recorded else {}
        accepted = fact.get("accepted")
        if type(accepted) is bool and task["state"] == ("succeeded" if accepted else "failed"):
            raise TaskVerificationRecorded(
                {
                    "eventId": recorded["id"],
                    "swarmId": args["swarmId"],
                    "taskId": task["id"],
                    "revision": task["revision"],
                    "runId": run["id"],
                    "accepted": accepted,
                    "taskState": task["state"],
                }
            )
        raise DomainError("TASK_NOT_WAITING_VERIFICATION", 409)
    return task, run, required


def fully_read(db, item, binding):
    if row(
        db,
        "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=?",
        (binding["owner"], item["sha256"]),
    ):
        raise DomainError("ARTIFACT_SOURCE_UNAVAILABLE", 409)
    receipts = rows(
        db,
        "SELECT x.id AS call_id,m.id AS result_id,m.content_json FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
        "JOIN messages current ON current.id=? WHERE x.turn_id=? AND x.tool_name='artifact_read' "
        "AND json_extract(x.arguments_json,'$.id')=? AND x.state='succeeded' "
        "AND x.assistant_message_id!=current.id AND m.seq<current.seq "
        "AND m.conversation_id=? AND current.conversation_id=m.conversation_id "
        "AND current.role='assistant' AND current.turn_id=x.turn_id AND m.role='tool' "
        "AND m.deleted_ms IS NULL ORDER BY m.seq",
        (
            binding.get("assistantMessageId"),
            binding["turnId"],
            item["id"],
            binding["conversation"],
        ),
    )
    return (
        text_coverage(
            receipts,
            {"id": item["id"], "sha256": item["sha256"], "size_bytes": item["sizeBytes"]},
        )
        is not None
    )


async def verify(swarms, confirm, artifacts, args, binding):
    if not args["checks"].strip():
        raise DomainError("SWARM_VERIFICATION_CHECKS_REQUIRED", 409)
    async with swarms.lock(args["swarmId"]):
        task, run, required = await swarms.db.call(lambda db: admission(db, args, binding))
        selected = []
        if args["accepted"]:
            available = await swarms.db.call(lambda db: evidence(db, task, run))
            selected = [item for item in available if item["id"] in args["artifactIds"]]
            if (
                not selected
                or len(selected) != len(args["artifactIds"])
                or any(
                    not any(
                        item["sizeBytes"] > 0
                        and (
                            not requirement.get("mimeType")
                            or item["mimeType"] == requirement["mimeType"]
                        )
                        for item in selected
                    )
                    for requirement in required
                    if requirement["kind"] == "artifact"
                )
            ):
                raise DomainError("SWARM_DELIVERABLE_EVIDENCE_REQUIRED", 409)
            for item in selected:
                try:
                    await artifacts.verified_path(binding["owner"], item["id"])
                except (DomainError, OSError):
                    raise DomainError("SWARM_DELIVERABLE_EVIDENCE_REQUIRED", 409) from None

        def ready(db):
            admission(db, args, binding)
            if any(not fully_read(db, item, binding) for item in selected):
                raise DomainError("SWARM_ARTIFACT_REVIEW_REQUIRED", 409)

        await swarms.db.call(ready)
        result = await confirm(
            binding["owner"],
            task["id"],
            args["accepted"],
            revision=args["revision"],
            run_id=run["id"],
        )

        def record(db):
            current = row(db, "SELECT revision,state FROM tasks WHERE id=?", (task["id"],))
            expected = "succeeded" if args["accepted"] else "failed"
            if current["revision"] != args["revision"] or current["state"] != expected:
                raise DomainError("TASK_RESULT_SUPERSEDED", 409)
            event(
                db,
                binding["conversation"],
                "swarm.verification_recorded",
                {
                    "swarmId": args["swarmId"],
                    "taskId": task["id"],
                    "revision": args["revision"],
                    "runId": run["id"],
                    "reviewer": "main",
                    "mainConversationId": binding["conversation"],
                    "mainTurnId": binding["turnId"],
                    "accepted": args["accepted"],
                    "checks": args["checks"].strip(),
                    "artifactIds": [item["id"] for item in selected],
                    "artifactSha256": {item["id"]: item["sha256"] for item in selected},
                },
                task_id=task["id"],
                turn_id=binding["turnId"],
            )

        await swarms.db.call(record, write=True)
        return {
            **result,
            "revision": args["revision"],
            "runId": run["id"],
            "checks": args["checks"].strip(),
            "artifactIds": [item["id"] for item in selected],
        }
