"""Native task bindings confined to the outer evaluation container's owned workspace."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows
from roami_agent.storage.task_handoff import accepted_handoffs

NATIVE_TASK_REQUEST = "本次任务明确使用内置Native Worker执行。"
NATIVE_TASK_PROFILE_VERSION = "native-worker-v2-continuations"
NATIVE_TASK_TOOLS = frozenset(
    {
        "delegate",
        "task_status",
        "task_reply",
        "task_queue_reply",
        "conversation_history",
        "task_steer",
    }
)
NATIVE_BUDGET_FAILURES = frozenset(
    {"RSI_TOKEN_BUDGET", "RSI_REQUEST_BUDGET", "RSI_TIME_BUDGET", "RSI_USAGE_UNKNOWN"}
)
NATIVE_EXECUTION_FAILURES = NATIVE_BUDGET_FAILURES | {
    "RSI_NATIVE_TASK_REQUIRED",
    "RSI_NATIVE_EXECUTOR_REQUIRED",
    "RSI_NATIVE_TASK_INCOMPLETE",
    "RSI_NATIVE_DELIVERY_REQUIRED",
}


async def delivered_evaluation_answer(database, turn_id):
    def read(db):
        handoffs = accepted_handoffs(db, turn_id)
        if not handoffs:
            return None
        results = rows(
            db,
            "SELECT t.id AS task_id,m.content_json FROM turns source JOIN conversations c ON c.id=source.conversation_id "
            "JOIN tasks t ON t.owner_id=c.owner_id AND t.origin_conversation_id=c.id "
            "AND t.origin_branch_id=source.branch_id "
            "JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision "
            "AND a.attempt_no=(SELECT MAX(last.attempt_no) FROM task_attempts last "
            "WHERE last.task_id=t.id AND last.task_revision=t.revision) "
            "JOIN jobs j ON j.kind='turn.run' "
            "AND json_extract(j.payload_json,'$.completion.taskId')=t.id "
            "AND json_extract(j.payload_json,'$.completion.taskRevision')=t.revision "
            "AND json_extract(j.payload_json,'$.completion.runId')=a.id "
            "JOIN turns u ON u.id=j.aggregate_id AND u.conversation_id=c.id "
            "AND u.branch_id=source.branch_id AND u.trigger_kind='completion' AND u.state='completed' "
            "JOIN messages m ON m.turn_id=u.id AND m.role='assistant' AND m.status='completed' "
            "AND m.deleted_ms IS NULL WHERE source.id=? AND t.id IN (SELECT value FROM json_each(?)) "
            "AND t.state IN ('succeeded','waiting_user') AND a.state='succeeded' AND a.executor_kind='native' "
            "AND json_extract(native_content(a.result_json),'$.outcomeKnown') IS NOT 0 "
            "AND json_extract(native_content(a.result_json),'$.inputStopped') IS NOT 0 "
            "AND json_extract(native_content(m.content_json),'$.source')='task' "
            "AND json_type(native_content(m.content_json),'$.answerText')='text' "
            "AND json_extract(native_content(m.content_json),'$.tool_calls') IS NULL "
            "ORDER BY m.rowid DESC",
            (turn_id, json.dumps(sorted(handoffs))),
        )
        if {result["task_id"] for result in results} != set(handoffs):
            return None
        return json.loads(results[0]["content_json"])["answerText"]

    return await database.call(read)


async def evaluation_turn_failure(database, turn):
    failure = await database.call(
        lambda db: db.execute(
            "SELECT json_extract(payload_json,'$.error') FROM events "
            "WHERE turn_id=? AND conversation_id=? AND kind=? ORDER BY rowid DESC LIMIT 1",
            (turn["id"], turn["conversation_id"], "turn." + turn["state"]),
        ).fetchone()
    )
    code = failure[0] if failure else None
    return (
        code
        if isinstance(code, str) and code in NATIVE_BUDGET_FAILURES
        else "RSI_TURN_" + turn["state"].upper()
    )


def bind_evaluation_tasks(runtime, workspace):
    root = workspace.resolve()
    # Keep internal task controls reachable without admitting Main's OS shell.
    runtime.tools.shell_disabled_roles.add("main")
    for name in ("shell", "write", "edit", "file_write", "file_patch"):
        if name in runtime.tools.registry:
            runtime.tools.registry[name].main = False

    @asynccontextmanager
    async def prepared(settings, task, run, *, stopped=None):
        target = json.loads(task["intent_json"])["target"]
        require(
            target["kind"] == "new_session"
            and target.get("nodeId", "local") == "local"
            and not target.get("resourceOnly")
            and bool(target.get("directory"))
            and Path(target["directory"]).resolve() == root,
            "RSI_TASK_WORKSPACE_REQUIRED",
        )
        try:
            # The outer Docker lifetime owns this directory; no Go/tmux lease is created.
            yield {"workspaceId": "rsi-" + task["id"], "directory": str(root), "projectId": None}
        finally:
            if stopped is not None:
                require(await stopped(), "RSI_TASK_WRITE_UNKNOWN")

    runtime.dispatch.native_executor.workspace_factory = prepared


async def verify_native_execution(database):
    attempts = await database.call(
        lambda db: [
            dict(r)
            for r in db.execute(
                "SELECT t.id,t.state AS task_state,a.executor_kind,a.state AS attempt_state "
                "FROM tasks t LEFT JOIN task_attempts a ON a.task_id=t.id "
                "AND a.task_revision=t.revision AND a.attempt_no=(SELECT MAX(last.attempt_no) "
                "FROM task_attempts last WHERE last.task_id=t.id AND last.task_revision=t.revision)"
            )
        ]
    )
    require(bool(attempts), "RSI_NATIVE_TASK_REQUIRED")
    require(all(a["executor_kind"] == "native" for a in attempts), "RSI_NATIVE_EXECUTOR_REQUIRED")
    require(
        all(
            a["task_state"] in {"waiting_user", "succeeded"} and a["attempt_state"] == "succeeded"
            for a in attempts
        ),
        "RSI_NATIVE_TASK_INCOMPLETE",
    )
    return attempts


async def settle_evaluation_tasks(database):
    while True:
        states = await database.call(
            lambda db: [r[0] for r in db.execute("SELECT state FROM tasks")]
        )
        if any(s in {"failed", "cancelled", "interrupted"} for s in states):
            failures = await database.call(
                lambda db: [
                    r[0]
                    for r in db.execute(
                        "SELECT a.result_json FROM tasks t JOIN task_attempts a ON a.task_id=t.id "
                        "AND a.task_revision=t.revision WHERE t.state='failed' AND a.state='failed' "
                        "AND a.attempt_no=(SELECT MAX(last.attempt_no) FROM task_attempts last "
                        "WHERE last.task_id=t.id AND last.task_revision=t.revision) ORDER BY t.created_ms,t.id"
                    )
                ]
            )
            for result in failures:
                value = json.loads(result) if result else None
                summary = value.get("summary") if isinstance(value, dict) else None
                if isinstance(summary, str) and summary in NATIVE_BUDGET_FAILURES:
                    raise DomainError(summary)
            raise DomainError("RSI_NATIVE_TASK_FAILED")
        active = await database.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM jobs WHERE kind IN ('turn.run','task.run','task.verify') AND state IN ('queued','running')"
            ).fetchone()[0]
        )
        if not active and all(s in {"succeeded", "waiting_user"} for s in states):
            return
        await asyncio.sleep(0.01)
