"""Atomic turn claims for serialized conversation branches."""

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
