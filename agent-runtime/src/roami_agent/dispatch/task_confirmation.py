"""Recheck bound execution evidence independently of result acceptance."""

import asyncio

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def reconcile_task(dispatch, owner, task_id, revision, run_id):
    task = await dispatch.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
    )
    if not task:
        raise DomainError("TASK_NOT_FOUND", 404)
    if task["revision"] != revision:
        raise DomainError("TASK_REVISION_CHANGED", 409)
    run = await dispatch.db.call(
        lambda db: row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (task_id, revision),
        )
    )
    if not run or run["id"] != run_id:
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    uncertain = run["state"] == "unknown" or (
        task["state"] == "cancelling" and run["state"] == "stopping"
    )
    if task["state"] not in {"preparing", "running", "cancelling"} or not uncertain:
        return {"taskId": task_id, "state": task["state"]}
    if run["executor_kind"] != "cli" or not getattr(dispatch.executor, "can_reconcile", False):
        raise DomainError("TASK_RECONCILIATION_UNAVAILABLE", 409)
    try:
        receipt = await dispatch.executor.command("status", "--key", run["launch_id"])
        await dispatch.executor.record(task, run, receipt)
    except (DomainError, OSError, TimeoutError) as exc:
        raise DomainError("TASK_STOP_UNCONFIRMED", 409) from exc
    if receipt.get("result") is not None or receipt.get("state") != "running":
        await reconcile_confirmation(dispatch, owner, task, run, receipt=receipt)
    current = await dispatch.db.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
    )
    return {"taskId": task_id, "state": current["state"]}


async def reconcile_confirmation(dispatch, owner, task, run, *, receipt=None):
    try:
        if receipt is None:
            receipt = await dispatch.executor.command("status", "--key", run["launch_id"])
        if receipt.get("result") is None:
            receipt = await dispatch.executor.command(
                "reconcile-session", "--key", run["launch_id"]
            )
    except (DomainError, OSError, TimeoutError) as exc:
        raise DomainError("TASK_STOP_UNCONFIRMED", 409) from exc
    result = dispatch.executor.result(receipt)
    if (
        not result
        or result.get("inputStopped") is not True
        or result.get("outcomeKnown") is not True
    ):
        raise DomainError("TASK_STOP_UNCONFIRMED", 409)
    await dispatch.tasks.report(owner, task["id"], run["id"], run["task_revision"], result)
    job = await dispatch.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=? "
            "AND json_extract(payload_json,'$.runId')=?",
            (task["id"], run["id"]),
        )
    )
    if not job:
        return
    if active := dispatch.active.get(job["id"]):
        await asyncio.shield(active["handle"])
    elif job["state"] == "queued":
        handle = asyncio.current_task()
        dispatch.active[job["id"]] = {
            "handle": handle,
            "group": "worker",
            "branch": None,
            "task": task["id"],
            "kind": "task.verify",
            "memory": False,
            "directory": None,
        }
        try:
            await dispatch.verify(job)
        finally:
            dispatch.active.pop(job["id"], None)
            dispatch.wakeup.set()
