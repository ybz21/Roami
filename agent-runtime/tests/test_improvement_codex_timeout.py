"""Keep Codex deadlines specific, private, and non-replayable through report failure."""

import json
import sys
from functools import partial

import pytest
from test_improvement_pipeline import setup_run

from roami_agent.improvement.integrations.codex_cli import run_codex
from roami_agent.improvement.workflows.codex_roles import codex_json
from roami_agent.improvement.workflows.pipeline_reports import PipelineReportWorker
from roami_agent.protocol.errors import DomainError


async def test_real_process_timeout_keeps_private_journal_and_specific_code(tmp_path):
    argv = [sys.executable, "-c", "import time; print('started',flush=True); time.sleep(60)"]
    with pytest.raises(DomainError, match="RSI_CODEX_TIMEOUT"):
        await run_codex(argv, cwd=tmp_path, timeout=0.3, max_bytes=1000)
    receipt = tmp_path / "process-failure.json"
    assert json.loads(receipt.read_text()) == {
        "code": "RSI_CODEX_TIMEOUT",
        "timeout_seconds": 0.3,
        "usage": "unknown",
    }
    assert receipt.stat().st_mode & 0o077 == 0
    assert (tmp_path / "journal/stdout").read_text() == "started\n"
    assert (tmp_path / "journal/stderr").is_file()


async def test_report_timeout_keeps_summary_unknown_cost_and_no_paid_replay(tmp_path, monkeypatch):
    service, run_id = setup_run(tmp_path)
    service.ledger.shared_daily_limit = True
    records = service.runs
    records.artifact("local", run_id, "evaluate", "evaluation-summary.md", "# Saved summary")
    records.set_state("local", run_id, "report_queued", {"cases": 1, "passed": 0})
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    calls = []

    async def timeout(argv, **kwargs):
        calls.append(1)
        return await run_codex(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=kwargs["cwd"],
            timeout=0.3,
            max_bytes=1000,
        )

    monkeypatch.setattr(
        "roami_agent.improvement.workflows.pipeline_reports.codex_json",
        partial(codex_json, runner=timeout),
    )
    from test_improvement_codex_gateway import plan

    from roami_agent.server.configuration import Settings

    async def resolve(*args, **kwargs):
        return plan([])

    monkeypatch.setattr("roami_agent.improvement.workflows.codex_roles.gateway_plan", resolve)
    worker = PipelineReportWorker(service, settings=Settings())
    await worker.execute(records.claim_report())
    blocked = records.get("local", run_id)
    assert blocked["state"] == "blocked"
    assert (
        next(n for n in blocked["nodes"] if n["node"] == "review")["error_code"]
        == "RSI_CODEX_TIMEOUT"
    )
    summary = next(a for a in blocked["artifacts"] if a["name"] == "evaluation-summary.md")
    assert records.read_artifact("local", run_id, summary["id"])["text"] == "# Saved summary"
    assert not any(a["name"] == "review.md" for a in blocked["artifacts"])
    assert blocked["summary"]["codex_tokens"] is None
    await worker.execute({"owner": "local", "id": run_id})
    assert calls == [1]
    replayed = records.get("local", run_id)
    assert (
        next(n for n in replayed["nodes"] if n["node"] == "review")["error_code"]
        == "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"
    )
