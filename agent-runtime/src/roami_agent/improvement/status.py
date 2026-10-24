"""Read-only owner-scoped experiment summaries for the Roami gateway."""

import asyncio
import json

from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.ledger import Ledger
from roami_agent.improvement.releases import Releases
from roami_agent.improvement.run_records import RunRecords
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
        self.runs = RunRecords(self.ledger)
        self.report_worker = None

    async def overview(self, owner):
        def read():
            return {
                "preferences": self.control.preferences(owner),
                "catalog": self.control.catalog(owner),
                "releases": self.releases.list(owner),
                "requests": self.control.requests(owner),
                "cycles": self.ledger.list(owner),
                "research": self.research.snapshot(owner),
                "pipeline": self.runs.view(owner),
            }

        return await asyncio.to_thread(read)

    async def list(self, owner, limit=20):
        return {
            "version": 1,
            "cycles": await asyncio.to_thread(self.ledger.list, owner, limit),
            "live_policy_automatically_modified": False,
        }

    async def get(self, owner, cycle_id):
        if cycle_id.startswith("period-"):
            report = await asyncio.to_thread(self.research.report, owner, cycle_id)
            return {
                "id": cycle_id,
                "state": "completed",
                "day": report["day"],
                "report": None,
                "review_document": report["document"],
            }
        cycle = await asyncio.to_thread(self.ledger.get, owner, cycle_id)

        # Hidden tasks' prompts, outputs, oracle and trial traces are absent from this endpoint.
        def document():
            with self.ledger.connection() as db:
                row = db.execute(
                    "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                    (owner, cycle_id),
                ).fetchone()
                return json.loads(row[0])["document"] if row else None

        return {
            **{k: cycle[k] for k in ("id", "state", "day", "report")},
            "review_document": await asyncio.to_thread(document),
        }
