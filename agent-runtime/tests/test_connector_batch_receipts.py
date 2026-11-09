import copy
import hashlib
import json

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke

from roami_agent.protocol.errors import DomainError
from roami_agent.tools.connector_batch_receipts import connector_batch_receipt

coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture
BATCH = "a" * 32


def workspace():
    receipt = {
        "id": BATCH,
        "connectorId": "bili-project",
        "sourceIdentity": "bilibili:account:project-a",
        "requestSha256": "b" * 64,
        "packageSha256": "c" * 64,
        "revision": 48,
        "publishedAt": "2026-11-09T05:51:03Z",
        "capturedAt": "2026-11-09T05:47:09Z",
        "date": "2026-11-09",
        "windowStart": "2026-11-09T05:47:09Z",
        "windowEnd": "2026-11-09T05:47:09Z",
        "observationIds": [f"observation-{i}" for i in range(6)],
        "evidence": [{"path": "long-evidence-path/" * 400}],
    }
    return {
        "projectId": "project-a",
        "revision": 51,
        "projectFiles": {"teamMemory": "", "teamMemorySha256": hashlib.sha256(b"").hexdigest()},
        "connectorBatches": [receipt],
        "observations": [{"value": i} for i in range(77)],
    }


@pytest.mark.parametrize(
    "fault", [None, "missing", "duplicate", "digest", "revision", "observations"]
)
def test_confirmed_receipt_survives_later_revision_without_large_context(fault):
    current = workspace()
    if fault == "duplicate":
        current["connectorBatches"] *= 2
    elif fault == "digest":
        current["connectorBatches"][0]["requestSha256"] = "invalid"
    elif fault == "revision":
        current["connectorBatches"][0]["revision"] = 52
    elif fault == "observations":
        current["connectorBatches"][0]["observationIds"] *= 2
    before = copy.deepcopy(current)
    if fault in {"duplicate", "digest", "revision", "observations"}:
        with pytest.raises(DomainError, match="CONNECTOR_BATCH_RECEIPT_UNAVAILABLE"):
            connector_batch_receipt(current, BATCH)
    else:
        result = connector_batch_receipt(current, "f" * 32 if fault == "missing" else BATCH)
        assert result["revision"] == 51
        assert result["status"] == ("not_found" if fault == "missing" else "confirmed")
        if not fault:
            assert result["receipt"]["revision"] == 48
            assert len(json.dumps(result)) < 2000
            assert "observations" not in result and "evidence" not in result["receipt"]
    assert current == before


async def test_original_main_reads_receipt_through_actual_coordinated_cli(
    coordinated_tools, monkeypatch
):
    runtime, team, _, _, _, binding = coordinated_tools
    current = workspace()
    before = copy.deepcopy(current)
    calls = []

    async def context(swarms, owner, sid, **kwargs):
        assert owner == "alice" and sid == team["id"]
        calls.append(kwargs)
        return current

    monkeypatch.setattr("roami_agent.storage.swarm_memory.project_context", context)
    args = {"swarmId": team["id"], "batchId": BATCH}
    result = await invoke(
        runtime,
        binding,
        "bash",
        {"argv": ["roami", "swarm", "connector", "batch", "--input", json.dumps(args)]},
    )
    assert result["status"] == "confirmed" and result["receipt"]["revision"] == 48
    listed = await invoke(runtime, binding, "tool_list", {"query": "swarm_connector_batch"})
    assert any(item["name"] == "swarm_connector_batch" for item in listed["items"])
    handler = runtime.tools.registry["swarm_connector_batch"].handler
    ordinary = {"owner": "alice", "conversation": team["mainConversationId"]}
    assert (
        await invoke(
            runtime,
            ordinary,
            "bash",
            {"argv": ["roami", "swarm", "connector", "batch", "--input", json.dumps(args)]},
        )
        == result
    )
    for denied in [
        {**ordinary, "owner": "bob"},
        {**ordinary, "conversation": "other-main"},
        {**ordinary, "taskId": "worker-task"},
    ]:
        with pytest.raises(DomainError):
            await handler(args, denied)
    assert len(calls) >= 2 and all(call == {} for call in calls) and current == before


@pytest.mark.parametrize("known", [True, False])
async def test_record_conflict_explains_existing_confirmation_without_retry(
    coordinated_tools, monkeypatch, known
):
    runtime, team, _, _, _, binding = coordinated_tools
    current = workspace()
    before = copy.deepcopy(current)
    calls = []
    if not known:
        current["connectorBatches"] = []

    async def context(swarms, owner, sid, **kwargs):
        calls.append(kwargs)
        if kwargs.get("operation") == "record":
            raise DomainError("OKR_CONFLICT", 409)
        return current

    monkeypatch.setattr("roami_agent.storage.swarm_memory.project_context", context)
    args = {
        "swarmId": team["id"],
        "operation": "record",
        "payload": {"revision": 51, "batch": {"id": BATCH, "note": "changed note"}},
    }
    with pytest.raises(
        DomainError,
        match="CONNECTOR_BATCH_ALREADY_CONFIRMED_REQUEST_CONFLICT" if known else "OKR_CONFLICT",
    ):
        await invoke(runtime, binding, "swarm_project_update", args)
    writes = [index for index, call in enumerate(calls) if call.get("operation") == "record"]
    assert len(writes) == 1 and calls[writes[0] + 1 :] == [{}]
    assert current["observations"] == before["observations"]


async def test_failed_receipt_read_preserves_original_conflict(coordinated_tools, monkeypatch):
    runtime, team, _, _, _, binding = coordinated_tools
    writes = []

    async def context(swarms, owner, sid, **kwargs):
        if kwargs.get("operation") == "record":
            writes.append(kwargs)
            raise DomainError("OKR_CONFLICT", 409)
        if writes:
            raise DomainError("SWARM_PROJECT_MEMORY_UNAVAILABLE", 503)
        return workspace()

    monkeypatch.setattr("roami_agent.storage.swarm_memory.project_context", context)
    with pytest.raises(DomainError, match="^OKR_CONFLICT$"):
        await invoke(
            runtime,
            binding,
            "swarm_project_update",
            {
                "swarmId": team["id"],
                "operation": "record",
                "payload": {"revision": 51, "batch": {"id": BATCH}},
            },
        )
    assert len(writes) == 1


async def test_host_workspace_cannot_return_another_projects_confirmation(
    coordinated_tools, monkeypatch
):
    runtime, team, _, _, _, binding = coordinated_tools
    current = workspace()
    current["projectId"] = "project-b"

    async def context(*args, **kwargs):
        return current

    monkeypatch.setattr("roami_agent.storage.swarm_memory.project_context", context)
    with pytest.raises(DomainError, match="SWARM_PROJECT_SCOPE_CONFLICT"):
        await invoke(
            runtime, binding, "swarm_connector_batch", {"swarmId": team["id"], "batchId": BATCH}
        )
