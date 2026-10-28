"""Read-only owner-scoped experiment summaries for the Roami gateway."""

import asyncio

from roami_agent.improvement.persistence.control import ImprovementControl
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.persistence.releases import Releases
from roami_agent.improvement.persistence.research_projection import ResearchProjection
from roami_agent.improvement.persistence.research_repository import ResearchRepository
from roami_agent.improvement.persistence.run_repository import RunRepository
from roami_agent.improvement.presentation.status import get_cycle, list_cycles, overview
from roami_agent.improvement.workflows.run_lifecycle import RunLifecycle


class ImprovementStatus:
    def __init__(self, data_root):
        self.ledger = Ledger(data_root / "agents" / "improvement" / "ledger.sqlite3")
        self.control = ImprovementControl(self.ledger)
        self.releases = Releases(self.ledger)
        self.wakeup = asyncio.Event()
        self.worker = None
        self.research = ResearchRepository(self.ledger)
        self.research_worker = None
        self.runs = RunRepository(self.ledger)
        self.run_lifecycle = RunLifecycle(self.runs, ResearchProjection(self.ledger))
        self.report_worker = None

    async def overview(self, owner):
        await asyncio.to_thread(self.run_lifecycle.sync_research, owner)
        return await overview(self, owner)

    async def list(self, owner, limit=20):
        return await list_cycles(self, owner, limit)

    async def get(self, owner, cycle_id):
        return await get_cycle(self, owner, cycle_id)
