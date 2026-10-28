"""Freeze public execution facts with the event, before a fast tool can finish."""

from roami_agent.conversation.activity import conversation_activity
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import history


def activity_event(db, cid, kind, payload, *, key=None, cascade=True, **refs):
    lifecycle = {
        "tool.started",
        "tool.completed",
        "task.activity",
        "task.accepted",
        "task.preparing",
        "task.started",
        "task.result",
        "task.succeeded",
        "task.failed",
        "task.cancelled",
        "task.interrupted",
        "task.waiting_user",
        "task.cancelling",
        "task.observation_unknown",
        "task.observation_recovered",
        "task.steered",
        "task.steer_cancelled",
    }
    # Workspace receipts are compared byte-for-byte by the existing idempotency guard.
    if kind not in lifecycle:
        return event(db, cid, kind, payload, key=key, **refs)
    task_id = refs.get("task_id") or payload.get("taskId")
    task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)) if task_id else None
    turn = (
        row(db, "SELECT * FROM turns WHERE id=?", (refs["turn_id"],))
        if refs.get("turn_id")
        else None
    )
    branch = (
        task["origin_branch_id"]
        if task and task["origin_conversation_id"] == cid
        else turn["branch_id"]
        if turn and turn["conversation_id"] == cid
        else None
    )
    ident = payload.get("activityId") or (
        "tool:" + payload["toolCallId"]
        if payload.get("toolCallId")
        else "task:" + payload["taskId"]
        if payload.get("taskId")
        else None
    )
    if branch and ident:
        activity = next(
            (a for a in conversation_activity(db, cid, history(db, branch)) if a["id"] == ident),
            None,
        )
        if activity:
            payload = {**payload, "activity": activity}
    event_id = event(db, cid, kind, payload, key=key, **refs)
    # Child lifecycle transitions belong in the originating Main Agent feed too.
    if (
        task
        and cascade
        and kind.startswith("task.")
        and (kind != "task.activity" or payload.get("activityId"))
    ):
        parent, seen = task, {cid}
        for _ in range(4):
            if not parent["parent_task_id"]:
                break
            parent = row(db, "SELECT * FROM tasks WHERE id=?", (parent["parent_task_id"],))
            if not parent:
                break
            origin = parent["origin_conversation_id"]
            if origin not in seen:
                activity_event(
                    db,
                    origin,
                    "task.activity",
                    {
                        "taskId": task["id"],
                        "sourceKind": kind,
                        **(
                            {"activityId": payload["activityId"]}
                            if payload.get("activityId")
                            else {}
                        ),
                    },
                    task_id=parent["id"],
                    cascade=False,
                    key=key + ":" + origin if key else None,
                )
                seen.add(origin)
    return event_id
