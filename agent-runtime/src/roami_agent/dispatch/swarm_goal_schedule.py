"""Verify existing node schedules before accepting a Main's explicit waiting decision."""

from roami_agent.executors.project_goal_schedule import schedule_identity
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.swarm_goal_schedule import check_wait, proposal, save_wait, wait_context


class GoalSchedule:
    def __init__(self, database, source):
        self.db, self.source = database, source

    async def wait(self, args, binding):
        context = await self.db.call(lambda db: wait_context(db, binding))
        reason = args["reason"].strip()
        if args["swarmId"] != context["scope"]["swarmId"] or not reason:
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        previous = await self.db.call(lambda db: proposal(db, binding))
        schedule = await self.source.read(context["scope"])
        if previous:
            if previous["reason"] != reason or any(
                previous.get(k) != v for k, v in context.items()
            ):
                raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
            if schedule_identity(previous["schedule"]) != schedule_identity(schedule):
                raise DomainError("GOAL_SCHEDULE_CHANGED", 409)
            schedule = previous["schedule"]
        return await self.db.call(
            lambda db: save_wait(db, binding, context, reason, schedule), write=True
        )

    async def current(self, binding):
        previous = await self.db.call(lambda db: proposal(db, binding))
        if previous is None:
            return None
        context = await self.db.call(lambda db: wait_context(db, binding))
        if any(previous.get(k) != v for k, v in context.items()):
            raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
        actual = await self.source.read(context["scope"])
        if schedule_identity(previous["schedule"]) != schedule_identity(actual):
            raise DomainError("GOAL_SCHEDULE_CHANGED", 409)
        return previous

    @staticmethod
    def check(db, binding, previous):
        check_wait(db, binding, previous)
