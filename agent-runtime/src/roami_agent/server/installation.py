"""Short-lived upgrade admission fence; in-flight work is never stopped for installation."""

import asyncio
import time

from roami_agent.protocol.errors import DomainError


class Installation:
    def __init__(self, runtime):
        self.runtime = runtime
        self.deadline = 0
        self.timer = None

    @property
    def active(self):
        return time.monotonic() < self.deadline

    def resume(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.deadline = 0
        self.runtime.settings.updating = False
        self.runtime.reconfiguring = False
        self.runtime.wakeup.set()

    async def quiesce(self, owner, body):
        runtime = self.runtime
        runtime.model_settings.owner(owner)
        if (
            not isinstance(body, dict)
            or set(body) != {"resume"}
            or type(body["resume"]) is not bool
        ):
            raise DomainError("INVALID_REQUEST")
        async with runtime.model_settings.lock:
            if body["resume"]:
                self.resume()
                return {"quiesced": False}
            runtime.settings.updating = True
            runtime.reconfiguring = True
            busy = await runtime.db.call(
                lambda db: db.execute(
                    "SELECT 1 FROM jobs WHERE state='running' UNION ALL "
                    "SELECT 1 FROM tasks WHERE state IN ('preparing','running','cancelling') LIMIT 1"
                ).fetchone()
            )
            if (
                busy
                or runtime.active
                or runtime.turn_tasks
                or runtime.briefs.lock.locked()
                or runtime.proactive.lock.locked()
            ):
                self.resume()
                raise DomainError("AGENT_UPGRADE_BUSY", 409)
            if self.timer:
                self.timer.cancel()
            self.deadline = time.monotonic() + 120
            self.timer = asyncio.get_running_loop().call_later(120, self.resume)
            return {"quiesced": True}
