"""Read-only owner-scoped experiment summaries for the Roami gateway."""

import asyncio

from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.ledger import Ledger
from roami_agent.improvement.releases import Releases
from roami_agent.improvement.workflow import ResearchWorkflow


class ImprovementStatus:
    def __init__(self, data_root):
        self.ledger = Ledger(data_root / "agents" / "improvement" / "ledger.sqlite3")
        self.control = ImprovementControl(self.ledger)
        self.releases = Releases(self.ledger)
        self.wakeup = asyncio.Event()
        self.worker = None
        self.research = ResearchWorkflow(self.ledger)
        self.research_worker = None

    async def overview(self, owner):
        def read():
            return {
                "preferences": self.control.preferences(owner),
                "catalog": self.control.catalog(owner),
                "releases": self.releases.list(owner),
                "requests": self.control.requests(owner),
                "cycles": self.ledger.list(owner),
                "research": self.research.snapshot(owner),
            }

        return await asyncio.to_thread(read)

    async def list(self, owner, limit=20):
        return {
            "version": 1,
            "cycles": await asyncio.to_thread(self.ledger.list, owner, limit),
            "live_policy_automatically_modified": False,
        }

    async def get(self, owner, cycle_id):
        cycle = await asyncio.to_thread(self.ledger.get, owner, cycle_id)
        # Hidden tasks' prompts, outputs, oracle and trial traces are absent from this endpoint.
        return {k: cycle[k] for k in ("id", "state", "day", "report")}
