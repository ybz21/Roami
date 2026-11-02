"""Keep the Go admission decision through transport, metering and conversation receipts."""

import json
import runpy
from pathlib import Path

import pytest
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume

from roami_agent.improvement.evaluation.conversation_scenarios import run_conversation
from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.protocol.errors import ModelAdmissionRejected
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings

REPOSITORY = Path(__file__).parents[3]
CONTROLS = json.loads((REPOSITORY / "cases/case-101-mech-gp01/input/decisions.json").read_text())


@pytest.mark.parametrize("code", CONTROLS["codes"])
async def test_trusted_admission_code_survives_runtime_and_summary(tmp_path, code):
    socket, seen = str(tmp_path / "gateway.sock"), []
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1",
        model="fixture",
        model_gateway_socket=socket,
        model_retries=3,
    )
    provider = configured_provider(settings, "main")
    scenario = json.loads(
        (REPOSITORY / "cases/case-95-chat-stack01/input/conversations.json").read_text()
    )["scenarios"][0]
    try:
        async with gateway_fixture(socket, seen, status=409, code=code):
            result = await run_conversation(
                scenario, tmp_path / "episode", settings=settings, provider=provider
            )
    finally:
        await provider.close()
    assert len(seen) == 1
    assert result["state"] == "blocked" and result["failure"] == code
    assert not result["live_model_semantics_tested"]
    assert result["checkpoints"][0]["semantic_checked"] is False
    assert result["metrics"]["request_attempts"] == result["metrics"]["observed_tokens"] == 0
    assert result["metrics"]["token_coverage"] == "complete"
    journal = json.loads((tmp_path / "episode/model-journal.json").read_text())
    assert journal[0]["error_code"] == code and journal[0]["admission_rejected"]
    summary = runpy.run_path(str(REPOSITORY / "scripts/dev/run-conversation-scenarios.py"))[
        "execution_summary"
    ]({"results": [result], "failure": None})
    assert summary["failure"] == code and summary["blocked_scenarios"] == 1


async def test_new_invocation_after_settlement_uses_same_provider_without_automatic_retry(tmp_path):
    socket, seen = str(tmp_path / "gateway.sock"), []
    provider = configured_provider(
        Settings(
            endpoint="https://must-not-connect.invalid/v1",
            model="fixture",
            model_gateway_socket=socket,
        ),
        "main",
    )
    budget = EpisodeBudget({"seconds": 30}, shared_daily_limit=True)
    journal = []
    model = MeteredModel(provider, budget, "main", journal=journal)
    try:
        async with gateway_fixture(socket, seen, status=409, code="MODEL_PROXY_USAGE_PENDING"):
            with pytest.raises(ModelAdmissionRejected) as error:
                await consume(model)
            assert error.value.code == "MODEL_PROXY_USAGE_PENDING"
            assert len(seen) == 1 and budget.metrics()["request_attempts"] == 0
        async with gateway_fixture(socket, seen):
            await consume(model)
    finally:
        await provider.close()
    assert len(seen) == len(journal) == 2
    assert journal[0]["admission_rejected"] and "admission_rejected" not in journal[1]
    assert budget.metrics()["request_attempts"] == 1
    assert budget.metrics()["token_coverage"] == "complete"


@pytest.mark.parametrize("code", CONTROLS["codes"])
async def test_completion_fallback_keeps_task_failure_separate_from_report_failure(
    store, tmp_path, code
):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    class RejectingExecutor:
        async def run(self, task, run):
            return {"state": "failed", "summary": "SESSION_NOT_IDLE"}

    socket, seen = str(tmp_path / "gateway.sock"), []
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1", model="fixture", model_gateway_socket=socket
    )
    provider = configured_provider(settings, "main")
    budget = EpisodeBudget({"seconds": 30}, shared_daily_limit=True)
    model = MeteredModel(provider, budget, "main", journal=[])
    runtime = Runtime(
        store,
        model,
        settings=settings,
        executor=RejectingExecutor(),
        memory_model=ConversationModel(),
    )
    try:
        async with gateway_fixture(socket, seen, status=409, code=code):
            conversation = await runtime.conversations.create("alice")
            task = await runtime.tasks.create(
                "alice",
                conversation["id"],
                "Continue",
                key="blocked-report",
                executor="codex",
                target={"kind": "session", "sessionId": "known"},
                record_intent=True,
            )
            await runtime.start()
            await until(
                store,
                lambda db: row(
                    db,
                    "SELECT id FROM messages WHERE json_extract(content_json,'$.taskStatus.taskId')=?",
                    (task["id"],),
                ),
            )
            view = await runtime.conversations.messages("alice", conversation["id"])
            facts = [
                m["content"]["taskStatus"] for m in view["messages"] if "taskStatus" in m["content"]
            ]
            assert facts == [
                {
                    "taskId": task["id"],
                    "state": "failed",
                    "errorCode": "SESSION_NOT_IDLE",
                    "reportError": code,
                }
            ]
            assert len(seen) == 1
            assert budget.metrics()["request_attempts"] == 0
    finally:
        await runtime.close()
        await provider.close()
