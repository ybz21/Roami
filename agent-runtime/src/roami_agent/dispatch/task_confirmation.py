"""Recheck the bound execution before accepting an unconfirmed report."""

import asyncio

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def reconcile_confirmation(dispatch, owner, task, run):
    try:
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
