"""Atomic turn claims for serialized conversation branches."""

import json

from roami_agent.conversation.project_wakeup import assert_main_idle
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import event, row
from roami_agent.storage.swarm_coordination import admitted_batch


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
            from roami_agent.storage.swarm_work_pause import conversation_paused

            if conversation_paused(db, turn["conversation_id"]):
                db.execute(
                    "UPDATE jobs SET available_ms=? WHERE id=?", (now_ms() + 1000, job["id"])
                )
                return None
            payload = json.loads(job["payload_json"])
            if turn["trigger_kind"] == "continuation" or payload.get("coordinationBatchId"):
                batch = row(
                    db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (turn["id"],)
                )
                if batch or payload.get("coordinationBatchId"):
                    try:
                        admitted_batch(db, turn["owner_id"], turn["id"])
                        conversation = row(
                            db, "SELECT * FROM conversations WHERE id=?", (turn["conversation_id"],)
                        )
                        assert_main_idle(db, conversation, ignore_turn_id=turn["id"])
                    except DomainError as exc:
                        if exc.code in {
                            "MAIN_BUSY",
                            "MAIN_WAITING_USER",
                            "SWARM_COORDINATION_PAUSED",
                        }:
                            db.execute(
                                "UPDATE jobs SET available_ms=? WHERE id=?",
                                (now_ms() + 1000, job["id"]),
                            )
                        else:
                            db.execute(
                                "UPDATE turns SET state='interrupted',finished_ms=? WHERE id=?",
                                (now_ms(), turn["id"]),
                            )
                            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                            event(
                                db,
                                turn["conversation_id"],
                                "turn.interrupted",
                                {"turnId": turn["id"], "error": exc.code},
                                turn_id=turn["id"],
                            )
                        return None
            completion = payload.get("completion")
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
            return dict(
                turn,
                state="running",
                lease_epoch=turn["lease_epoch"] + 1,
                resumed=bool(json.loads(job["payload_json"]).get("deferred")),
            )

        return await self.db.call(write, write=True)
