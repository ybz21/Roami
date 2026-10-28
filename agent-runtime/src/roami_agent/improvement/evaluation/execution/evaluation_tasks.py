"""Native task bindings confined to the outer evaluation container's owned workspace."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.errors import DomainError

NATIVE_TASK_REQUEST = "本次任务明确使用内置Native Worker执行。"
NATIVE_BUDGET_FAILURES = frozenset(
    {"RSI_TOKEN_BUDGET", "RSI_REQUEST_BUDGET", "RSI_TIME_BUDGET", "RSI_USAGE_UNKNOWN"}
)
NATIVE_EXECUTION_FAILURES = NATIVE_BUDGET_FAILURES | {
    "RSI_NATIVE_TASK_REQUIRED",
    "RSI_NATIVE_EXECUTOR_REQUIRED",
    "RSI_NATIVE_TASK_INCOMPLETE",
}


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
    # Host scope must not bypass this lane's explicit Native handoff.
    runtime.tools.registry["bash"].main = False

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
            yield {"workspaceId": "rsi-" + run["id"], "directory": str(root), "projectId": None}
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
