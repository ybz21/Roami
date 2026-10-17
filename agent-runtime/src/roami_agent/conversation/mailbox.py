"""Atomic turn claims for serialized conversation branches."""

import json

from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row


class TurnMailbox:
    def __init__(self, database):
        self.db = database

    async def claim(self, job):
        def write(db):
            turn = row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=? AND t.state='queued'",
                (job["aggregate_id"],),
            )
            if not turn:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                return None
            completion = json.loads(job["payload_json"]).get("completion")
            if completion and not row(
                db,
                "SELECT id FROM tasks WHERE id=? AND owner_id=? AND revision=? AND state=? AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.kind='task.steer' AND j.aggregate_id=tasks.id AND j.state='queued')",
                (
                    completion.get("taskId"),
                    turn["owner_id"],
                    completion.get("taskRevision", 1),
                    completion.get("state"),
                ),
            ):
                db.execute(
                    "UPDATE turns SET state='interrupted',finished_ms=? WHERE id=?",
                    (now_ms(), turn["id"]),
                )
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                return None
            if row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state='running'",
                (turn["branch_id"],),
            ):
                return None
            db.execute(
                "UPDATE turns SET state='running',lease_epoch=lease_epoch+1 WHERE id=?",
                (turn["id"],),
            )
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?", (job["id"],)
            )
            return turn

        return await self.db.call(write, write=True)
