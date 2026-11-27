"""Project date-slot admission over the existing Swarm job queue."""

from pydantic import Field

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.http import Payload
from roami_agent.server.http import Owner
from roami_agent.storage.swarm_daily_goal import date_slot, queue
from roami_agent.storage.swarm_delegations import current_delegation


class DailyGoalWake(Payload):
    delegationId: str = Field(min_length=1, max_length=200)
    projectId: str = Field(min_length=1, max_length=200)
    conversationId: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=100)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    slot: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    dryRun: bool = False


def mount_daily_routes(app, runtime):
    @app.post("/v1/swarms/{sid}/goal/daily")
    async def daily_goal(sid: str, body: DailyGoalWake, owner: Owner):
        def submit(db):
            goal = current_delegation(db, owner, sid, body.delegationId, allow_paused=True)
            if (
                goal["projectId"] != body.projectId
                or goal["mainConversationId"] != body.conversationId
            ):
                raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)
            marker = date_slot(goal["id"], timezone=body.timezone, slot=body.slot)
            if marker["date"] != body.date:
                raise DomainError("SWARM_DAILY_DATE_EXPIRED", 409)
            if body.dryRun:
                return {
                    "state": "prepared",
                    "delivered": False,
                    "swarmId": sid,
                    "dailySlot": marker,
                }
            return {
                "state": "accepted",
                "delivered": True,
                **queue(
                    db,
                    owner,
                    sid,
                    goal["id"],
                    timezone=body.timezone,
                    slot=body.slot,
                    expected_date=body.date,
                ),
            }

        result = await runtime.db.call(submit, write=not body.dryRun)
        if not body.dryRun:
            runtime.wakeup.set()
        return {"data": result}
