"""Runtime RSI exposes shared model spending instead of a second quota editor."""

import json

import httpx
import pytest
from test_improvement_control import suite_file

from roami_agent.app import Runtime
from roami_agent.improvement.operation_accounting import assert_operation_costs_settled
from roami_agent.improvement.status import ImprovementStatus
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app


class Model:
    model = "fixture"


@pytest.mark.parametrize(
    ("tokens", "shared", "accepted"), [(10, True, True), (None, True, False), (10, False, False)]
)
def test_legacy_known_receipts_can_exceed_old_reservations_only_under_shared_policy(
    tmp_path, tokens, shared, accepted
):
    service = ImprovementStatus(tmp_path)
    with service.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_operation_costs VALUES('legacy','local','day',1,'completed',?)",
            (json.dumps({"value": {"metrics": {"tokens": tokens}}}),),
        )
        if accepted:
            assert_operation_costs_settled(db, "local", shared=shared)
        else:
            with pytest.raises(DomainError, match="UNKNOWN_OPERATION"):
                assert_operation_costs_settled(db, "local", shared=shared)


async def test_runtime_settings_omit_quota_fields_and_keep_legacy_audit_values(store, tmp_path):
    runtime = Runtime(store, Model(), development_rsi=True)
    service = runtime.improvement
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "native_files"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://runtime",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        view = (await client.get("/v1/improvement")).json()["data"]
        assert (
            "daily_tokens" not in view["preferences"]
            and "daily_episodes" not in view["preferences"]
        )
        assert set(view["pipeline"]["settings"]) == {"revision", "auto_publish"}
        assert "model_tokens" not in view["research"]["settings"]
        assert "repo" not in view["research"]["settings"]
        response = await client.put(
            "/v1/improvement/preferences",
            json={**view["preferences"], "suite_id": "data", "machine_ids": ["a"]},
        )
        assert response.status_code == 200 and "daily_tokens" not in response.json()["data"]
        assert service.control.preferences("local")["daily_tokens"] == 0
        response = await client.put(
            "/v1/improvement/pipeline/settings",
            json={**view["pipeline"]["settings"], "daily_tokens": 1},
        )
        assert response.status_code == 200 and set(response.json()["data"]) == {
            "revision",
            "auto_publish",
        }
        assert service.runs.settings("local")["daily_tokens"] == 1000000
        response = await client.put(
            "/v1/improvement/research", json={**view["research"]["settings"], "model_tokens": 1}
        )
        assert response.status_code == 200 and "model_tokens" not in response.json()["data"]
        assert service.research.settings("local")["model_tokens"] == 64000
        response = await client.post(
            "/v1/improvement/requests",
            json={"machine_id": "a", "request_key": "shared-no-token-budget"},
        )
        assert response.status_code == 200
        assert service.control.requests("local")[0]["state"] == "queued"


@pytest.mark.parametrize(
    "state,expected", [("failed", "failed"), ("done", "succeeded"), ("unknown", "unknown")]
)
def test_research_action_keeps_actual_workflow_state(tmp_path, state, expected):
    service = ImprovementStatus(tmp_path)
    ident = service.runs.create("local", "formal-fixture", "manual", {})
    with service.ledger.connection() as db:
        db.execute("UPDATE rsi_pipeline_runs SET cycle_id='cycle' WHERE id=?", (ident,))
        action = service.research._enqueue(db, "local", "review", "cycle", {})
        db.execute("UPDATE rsi_actions SET state=? WHERE id=?", (state, action))
    service.runs.sync_research("local")
    stage = next(
        node for node in service.runs.get("local", ident)["nodes"] if node["node"] == "review"
    )
    assert stage["state"] == expected
    artifacts = service.runs.get("local", ident)["artifacts"]
    assert len(artifacts) == 1 and artifacts[0]["node"] == "review"
    receipt = json.loads(service.runs.read_artifact("local", ident, artifacts[0]["id"])["text"])
    assert receipt["state"] == state
    service.runs.sync_research("local")
    assert len(service.runs.get("local", ident)["artifacts"]) == 1


def test_stage_receipt_omits_private_repair_payload(tmp_path):
    service = ImprovementStatus(tmp_path)
    ident = service.runs.create("local", "receipt-fixture", "manual", {})
    with service.ledger.connection() as db:
        db.execute("UPDATE rsi_pipeline_runs SET cycle_id='cycle' WHERE id=?", (ident,))
        action = service.research._enqueue(db, "local", "repair", "cycle", {})
        db.execute(
            "UPDATE rsi_actions SET state='done',result_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "candidate_build_hash": "c" * 64,
                        "patch": "private fixture",
                        "private_answers": [42],
                    }
                ),
                action,
            ),
        )
    service.runs.sync_research("local")
    artifacts = service.runs.get("local", ident)["artifacts"]
    receipt = json.loads(service.runs.read_artifact("local", ident, artifacts[0]["id"])["text"])
    assert receipt["result"] == {"candidate_build_hash": "c" * 64}
