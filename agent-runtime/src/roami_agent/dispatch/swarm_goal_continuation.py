"""Require a real next step before an ongoing Main accepts its final reply."""

from roami_agent.dispatch.swarm_goal_continuity import (
    GoalContinuityReview,
    cached_policy,
    continuity_payload,
)
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_goal_checkpoint import (
    accepted_checkpoint,
    action_batch,
    active_next_steps,
    checkpoint_context,
    current_blocker,
    save_checkpoint,
)


class GoalContinuation:
    def __init__(self, database, reviewer, timezone_name, *, schedule=None):
        self.db, self.reviewer, self.timezone = database, reviewer, timezone_name
        self.schedule = schedule

    async def prepare(self, binding):
        def inspect(db):
            value = checkpoint_context(db, binding)
            if value is None:
                return None
            if not action_batch(value) and not row(
                db,
                "SELECT id FROM events WHERE turn_id=? AND kind='swarm.verification_recorded' LIMIT 1",
                (binding["turnId"],),
            ):
                return None
            return value

        value = await self.db.call(inspect)
        if value is None:
            return None
        previous = await self.db.call(lambda db: accepted_checkpoint(db, binding, value))
        if previous:
            if previous["decision"]["kind"] == "waiting_for_registered_schedule" and (
                self.schedule is None
                or await self.schedule.current(binding) != previous["decision"]["wait"]
            ):
                raise DomainError("GOAL_SCHEDULE_CHANGED", 409)
            return previous
        active = await self.db.call(lambda db: active_next_steps(db, binding))
        policy = None
        if not active["steps"]:
            policy = await GoalContinuityReview(self.db, self.reviewer(), self.timezone).inspect(
                binding
            )
        scheduled = (
            await self.schedule.current(binding) if self.schedule and not active["steps"] else None
        )

        def save(db):
            latest = inspect(db)
            if latest is None:
                raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
            current = active_next_steps(db, binding)
            if current["steps"]:
                decision = {"kind": "waiting_for_original_work", "steps": current["steps"]}
            else:
                payload = continuity_payload(db, binding, self.timezone)
                actual = cached_policy(db, binding, payload) if payload else None
                if not policy or actual != policy:
                    raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
                if scheduled and not policy["requiresNextStep"]:
                    self.schedule.check(db, binding, scheduled)
                    return save_checkpoint(
                        db,
                        binding,
                        {"kind": "waiting_for_registered_schedule", "wait": scheduled},
                    )
                if not policy["requiresNextStep"]:
                    decision = {
                        "kind": "reviewed_no_next_step",
                        "policyFingerprint": policy["sourceFingerprint"],
                    }
                else:
                    blocker = current_blocker(db, binding, latest)
                    if blocker is None:
                        raise DomainError("SWARM_GOAL_NEXT_STEP_REQUIRED", 409)
                    decision = {"kind": "blocked", "blocker": blocker}
            return save_checkpoint(db, binding, decision)

        return await self.db.call(save, write=True)
