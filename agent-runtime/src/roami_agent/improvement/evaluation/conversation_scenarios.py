"""Isolated Main intake, tools and task-state evaluation across complete conversations."""

import asyncio
import hashlib
import io
import json
import logging
from dataclasses import replace

from PIL import Image

from roami_agent.app import Runtime
from roami_agent.dispatch.routing import TaskRouter
from roami_agent.improvement.evaluation.conversation_actor import ScriptedConversationActor
from roami_agent.improvement.evaluation.conversation_oracle import grade_checkpoint
from roami_agent.improvement.evaluation.execution.executors import committed_answer
from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row, rows
from roami_agent.storage.task_request import task_user_request
from roami_agent.tools.main_catalog import register_main_tools
from roami_agent.tools.registry import Tools

log = logging.getLogger(__name__)

ALLOWED = {
    "read",
    "skill_read",
    "bash",
    "tool_list",
    "delegate",
    "ask_user",
    "reply",
    "conversation_history",
    "task_status",
    "task_steer",
    "task_reply",
    "task_queue_reply",
    "target_search",
    "target_resolve",
    "executor_catalog",
    "workspace_overview",
    "capability_overview",
    "artifact_read",
}


class ScenarioTargets:
    def __init__(self, root, database):
        self.root, self.database = root, database
        self.projects = [
            {"kind": "project", "projectId": "maple", "name": "枫林", "defaultExecutor": "codex"},
            {"kind": "project", "projectId": "cedar", "name": "雪松", "defaultExecutor": "claude"},
        ]

    async def executors(self, commands=None):
        return {
            "version": 1,
            "defaultExecutor": "codex",
            "observedMs": 1,
            "candidates": [
                {
                    "kind": kind,
                    "installed": True,
                    "tracked": True,
                    "authentication": "unknown",
                    "usage": "unknown",
                }
                for kind in ["codex", "claude"]
            ],
        }

    async def search(self, kind, query="", *, offset=0, limit=10, project_id=None):
        found = [
            item
            for item in self.projects
            if kind == "project"
            and (not query or query in item["name"] or query == item["projectId"])
        ]
        return {
            "kind": kind,
            "items": found[offset : offset + limit],
            "total": len(found),
            "nextOffset": offset + limit if len(found) > offset + limit else None,
        }

    async def resolve(self, kind, ident):
        if kind == "project":
            found = [p for p in self.projects if ident in {p["projectId"], p["name"]}]
            if len(found) == 1:
                return found[0]
        if kind == "session":
            task = await self.database.call(
                lambda db: row(
                    db,
                    "SELECT t.intent_json FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
                    "WHERE a.session_id=? ORDER BY a.attempt_no DESC LIMIT 1",
                    (ident,),
                )
            )
            if task:
                return {
                    "kind": kind,
                    "sessionId": ident,
                    "executor": json.loads(task["intent_json"])["executor"],
                }
        raise DomainError("PROJECT_NOT_FOUND" if kind == "project" else "SESSION_TARGET_NOT_FOUND")

    async def overview(self):
        return {"projects": {"total": len(self.projects)}, "sessions": {"total": 0}}

    async def send(self, *args, **kwargs):
        raise DomainError("RSI_SCENARIO_SESSION_SEND_UNAVAILABLE")


async def task_snapshot(runtime, cid, turn_id):
    def read(db):
        result = []
        turn_order = {
            item["id"]: index + 1
            for index, item in enumerate(
                rows(
                    db,
                    "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='user' ORDER BY rowid",
                    (cid,),
                )
            )
        }
        for task in rows(db, "SELECT * FROM tasks WHERE owner_id='rsi-evaluation' ORDER BY rowid"):
            intent = json.loads(task["intent_json"])
            binding = json.loads(task["target_json"] or "{}")
            names = set()
            user_contract = []
            for mid in dict.fromkeys(
                [*intent.get("sourceMessageIds", []), task["origin_message_id"]]
            ):
                source = task_user_request(db, row(db, "SELECT * FROM messages WHERE id=?", (mid,)))
                if source:
                    content = json.loads(source["content_json"])
                    user_contract.append(content.get("text", ""))
                    names.update(item["name"] for item in content.get("attachments", []))
            result.append(
                {
                    "id": task["id"],
                    "goal": intent["goal"],
                    "title": intent.get("title", ""),
                    "created_turn": turn_order.get(
                        intent.get("initialIntent", intent).get("sourceTurnId")
                    ),
                    "revision": task["revision"],
                    "executor": intent["executor"],
                    "conversation_id": task["origin_conversation_id"],
                    "attachments": sorted(names),
                    "user_contract": "\n".join(user_contract),
                    "project_id": binding.get("projectId")
                    or intent.get("target", {}).get("projectId"),
                    "binding": {
                        key: binding.get(key) for key in ["workspaceId", "workdir", "sessionId"]
                    },
                    "attempt_count": db.execute(
                        "SELECT count(*) FROM task_attempts WHERE task_id=?", (task["id"],)
                    ).fetchone()[0],
                    "current_run_count": db.execute(
                        "SELECT count(*) FROM task_attempts WHERE task_id=? AND task_revision=?",
                        (task["id"], task["revision"]),
                    ).fetchone()[0],
                }
            )
        turn = row(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
        questions = rows(
            db,
            "SELECT id FROM messages WHERE turn_id=? AND json_extract(content_json,'$.question') IS NOT NULL",
            (turn_id,),
        )
        return {
            "conversation_id": cid,
            "tasks": result,
            "turn_state": turn["state"],
            "question": bool(questions),
            "tools": [
                item["tool_name"]
                for item in rows(db, "SELECT tool_name FROM tool_calls WHERE turn_id=?", (turn_id,))
            ],
            "pending_steers": db.execute(
                "SELECT count(*) FROM jobs WHERE kind='task.steer' AND state='queued'"
            ).fetchone()[0],
        }

    snapshot = await runtime.db.call(read)
    view = await runtime.conversations.messages("rsi-evaluation", cid)
    snapshot["answer"] = committed_answer(view["messages"], turn_id=turn_id)
    return snapshot


async def complete_fixture_work(runtime, root):
    def write(db):
        for task in rows(db, "SELECT * FROM tasks WHERE state='queued'"):
            intent = json.loads(task["intent_json"])
            old = json.loads(task["target_json"] or "{}")
            directory = root / "workspaces" / task["id"]
            directory.mkdir(parents=True, exist_ok=True)
            session = old.get("sessionId", "scenario-session-" + task["id"])
            binding = {
                "workspaceId": old.get("workspaceId", "scenario-workspace-" + task["id"]),
                "workdir": str(directory),
                "sessionId": session,
                "projectId": old.get("projectId") or intent["target"].get("projectId"),
            }
            db.execute(
                "UPDATE tasks SET state='succeeded',target_json=? WHERE id=?",
                (json.dumps(binding), task["id"]),
            )
            db.execute(
                "UPDATE task_attempts SET state='succeeded',node_id='local',session_id=CASE WHEN executor_kind='cli' THEN ? END,result_json=?,finished_ms=1 WHERE task_id=? AND task_revision=?",
                (
                    session,
                    json.dumps(
                        {
                            "state": "succeeded",
                            "inputStopped": True,
                            "outcomeKnown": True,
                            "summary": "Synthetic executor checkpoint; no actual deliverable",
                        }
                    ),
                    task["id"],
                    task["revision"],
                ),
            )
        db.execute(
            "UPDATE jobs SET state='done' WHERE kind IN ('task.run','task.verify') AND state='queued'"
        )

    await runtime.db.call(write, write=True)


async def run_conversation(scenario, root, *, settings=None, provider=None):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    database = Database(root / "runtime.db", root / "runtime", managed=False)
    await database.open()
    actor = ScriptedConversationActor() if provider is None else None
    budget = EpisodeBudget({"seconds": scenario["seconds"]}, shared_daily_limit=True)
    journal = []
    selected = provider or actor
    model = MeteredModel(selected, budget, "main", journal=journal)
    base = settings or Settings(model_capabilities={"images": True})
    isolated = replace(
        base,
        workers=0,
        coding_directory=None,
        skill_roots=(),
        shell_roots=(),
        mcp_servers={},
        http_tools={},
        browser={},
        computer={},
        proactive_enabled=False,
    )
    runtime = Runtime(database, model, settings=isolated)
    targets = ScenarioTargets(root, database)
    registry = Tools(runtime.artifacts)
    register_main_tools(
        registry,
        runtime.tasks,
        runtime.memory,
        targets,
        TaskRouter(database, targets, runtime.settings, runtime.memory),
    )
    runtime.tools.registry.update(registry.registry)

    async def registered_only(args, binding):
        raise DomainError("RSI_SCENARIO_REGISTERED_COMMAND_REQUIRED")

    runtime.tools.registry["bash"] = replace(
        runtime.tools.registry["bash"], handler=registered_only
    )
    runtime.tools.disabled_tools.update(set(runtime.tools.registry) - ALLOWED)
    bindings, checkpoints, transcripts, identities = {}, [], [], {}
    failure = None
    try:
        conversation = await runtime.conversations.create("rsi-evaluation")
        async with asyncio.timeout(scenario["seconds"]):
            for index, step in enumerate(scenario["turns"]):
                artifacts = []
                for name in step.get("attachments", []):
                    body = io.BytesIO()
                    Image.new(
                        "RGB", (32, 24), tuple(hashlib.sha256(name.encode()).digest()[:3])
                    ).save(body, format="PNG")
                    artifacts.append(
                        await runtime.attachments.upload(
                            "rsi-evaluation", name, f"input-{index}-{name}", body.getvalue()
                        )
                    )
                receipt = await runtime.chat.submit(
                    "rsi-evaluation",
                    conversation["id"],
                    str(index),
                    step["text"],
                    [a["id"] for a in artifacts],
                )
                if step.get("replay"):
                    repeated = await runtime.chat.submit(
                        "rsi-evaluation",
                        conversation["id"],
                        str(index),
                        step["text"],
                        [a["id"] for a in artifacts],
                    )
                    if repeated["turnId"] != receipt["turnId"]:
                        raise DomainError("RSI_SCENARIO_INTAKE_DUPLICATED")
                job = await database.call(
                    lambda db, receipt=receipt: row(
                        db,
                        "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                        (receipt["turnId"],),
                    )
                )
                if actor:
                    actor.turn(step["fixture"])
                journal_start = len(journal)
                await runtime.scheduler._job(job)
                await runtime.tasks.revisions.advance()
                snapshot = await task_snapshot(runtime, conversation["id"], receipt["turnId"])
                turn_records = journal[journal_start:]
                semantic_checked = snapshot["turn_state"] == "completed"
                admission_rejected = any(r.get("admission_rejected") for r in turn_records)
                if semantic_checked:
                    grade = grade_checkpoint(step["expect"], snapshot, bindings)
                else:
                    failure = next(
                        (r["error_code"] for r in reversed(turn_records) if r.get("error_code")),
                        "RSI_SCENARIO_TURN_FAILED",
                    )
                    grade = {"passed": False, "failures": []}
                for task in snapshot["tasks"]:
                    identity = [task["executor"], task["project_id"], task["binding"]]
                    if task["id"] in identities and identities[task["id"]] != identity:
                        grade["passed"] = False
                        grade["failures"].append("TASK_BINDING_CHANGED")
                # Requirements arrive through intake only; queued future inputs must never be projected.
                future = {s["text"] for s in scenario["turns"][index + 1 :]}
                seen = {s["text"] for s in scenario["turns"][: index + 1]}
                prompts = [record["messages"] for record in journal if record.get("messages")]
                if prompts and any(
                    text in json.dumps(prompts, ensure_ascii=False) for text in future - seen
                ):
                    grade["passed"] = False
                    grade["failures"].append("FUTURE_USER_INPUT_LEAKED")
                if budget.metrics()["token_coverage"] != "complete":
                    failure = failure or "RSI_USAGE_UNKNOWN"
                checkpoints.append(
                    {
                        "turn": index + 1,
                        **grade,
                        "semantic_checked": semantic_checked,
                        "state": "blocked"
                        if (admission_rejected or failure == "RSI_USAGE_UNKNOWN")
                        and not grade["failures"]
                        else "passed"
                        if grade["passed"] and not failure
                        else "failed",
                        "failure": failure,
                    }
                )
                transcripts.append({"turn": index + 1, "snapshot": snapshot})
                if failure or not grade["passed"]:
                    break
                await complete_fixture_work(runtime, root)
                completed = await task_snapshot(runtime, conversation["id"], receipt["turnId"])
                identities = {
                    task["id"]: [task["executor"], task["project_id"], task["binding"]]
                    for task in completed["tasks"]
                }
    except Exception as error:
        log.exception("Conversation scenario failed")
        failure = getattr(error, "code", type(error).__name__)
    finally:
        await runtime.close()
        await database.close()
    result = {
        "scenario": scenario["id"],
        "contract_sha256": hashlib.sha256(
            json.dumps(scenario, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "mode": "protocol_fixture" if actor else "saved_main_model",
        "passed": failure is None
        and len(checkpoints) == len(scenario["turns"])
        and all(c["passed"] for c in checkpoints),
        "failure": failure,
        "state": "blocked"
        if checkpoints and checkpoints[-1]["state"] == "blocked"
        else "passed"
        if failure is None
        and len(checkpoints) == len(scenario["turns"])
        and all(c["passed"] for c in checkpoints)
        else "failed",
        "expected_turns": len(scenario["turns"]),
        "checkpoints": checkpoints,
        "metrics": budget.metrics(),
        "background_execution": "synthetic_checkpoint",
        "live_model_semantics_tested": actor is None
        and any(c["semantic_checked"] for c in checkpoints),
        "eligible_for_promotion": False,
    }
    for name, value in [
        ("receipt.json", result),
        ("transcript.json", transcripts),
        ("model-journal.json", journal),
    ]:
        path = root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)
    return result
