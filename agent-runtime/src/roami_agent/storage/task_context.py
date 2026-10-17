"""Exclude forgotten task provenance from model-facing status responses."""

from roami_agent.storage.database import row


def model_task_projection(db, owner, tasks):
    result = []
    for task in tasks:
        source = row(
            db,
            "SELECT origin_message_id FROM tasks WHERE id=? AND owner_id=?",
            (task["id"], owner),
        )
        if not source or row(
            db,
            "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
            (owner, source["origin_message_id"]),
        ):
            result.append({"id": task["id"], "state": task["state"], "contextExcluded": True})
        else:
            result.append(task)
    return result
