"""Fresh model calls cannot change the host's project-write business identity."""

import json

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_memory import digest

coordination = coordination_fixture
coordinated_tools = coordinated_tools_fixture
delegated_team = delegated_team_fixture


@pytest.fixture
async def project_transport(coordinated_tools, monkeypatch):
    runtime, team, _, _, _, binding = coordinated_tools
    calls = []

    async def execute(argv, **kwargs):
        payload = json.loads(kwargs["input_data"]) if kwargs.get("input_data") else None
        if payload is not None:
            calls.append((argv, payload))
        files = {
            "operationReceiptsSupported": True,
            "teamMemory": "Original knowledge",
            "teamMemorySha256": digest("Original knowledge"),
        }
        if payload and payload.get("mode") == "append":
            files["operationReceipt"] = {
                "key": payload["operationKey"],
                "kind": "memory_append",
                "requestSha256": "a" * 64,
                "previousSha256": "b" * 64,
                "resultSha256": "c" * 64,
                "recordedAt": "2026-11-07T00:00:00Z",
            }
        workspace = {
            "projectId": "project-a",
            "revision": 2,
            "projectFiles": files,
            "irrelevantLargeGuidance": "large" * 30000,
        }
        if payload and "operationKey" in payload and payload.get("mode") != "append":
            files["operationReceipt"] = {
                "key": payload["operationKey"],
                "kind": "review" if "summary" in payload else "observation",
                "reviewId" if "summary" in payload else "observationId": "actual-project-fact",
                "requestSha256": "a" * 64,
                "recordedAt": "2026-11-07T00:00:00Z",
            }
        if payload and "batch" in payload:
            workspace["connectorBatches"] = [
                {
                    "id": payload["batch"]["id"],
                    "requestSha256": "b" * 64,
                    "observationIds": ["actual-observation"],
                }
            ]
        return {"exitCode": 0, "stdout": json.dumps({"data": workspace})}

    monkeypatch.setattr("roami_agent.storage.swarm_memory.execute", execute)
    batch = await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (binding["turnId"],)
        )
    )
    return runtime, team, binding, batch["id"], calls


@pytest.mark.parametrize("alias", ["swarm_project_update", "bash"])
async def test_review_key_ignores_new_call_and_fresh_revision(project_transport, alias):
    runtime, team, binding, batch_id, calls = project_transport
    args = {
        "swarmId": team["id"],
        "operation": "review",
        "payload": {"revision": 1, "summary": "Actual evidence", "actions": "Next original round"},
    }

    def wire(value):
        return (
            value
            if alias != "bash"
            else {"argv": ["roami", "swarm", "project", "update", "--input", json.dumps(value)]}
        )

    result = await invoke(runtime, binding, alias, wire(args))
    assert result["operationReceipt"]["key"] == "coordination:" + batch_id + ":review"
    assert "outputExternalized" not in result and "irrelevantLargeGuidance" not in result
    await invoke(
        runtime,
        {**binding, "toolCallId": "fresh-call"},
        alias,
        wire({**args, "payload": {**args["payload"], "revision": 2}}),
    )
    assert [body["operationKey"] for _, body in calls] == [
        "coordination:" + batch_id + ":review"
    ] * 2
    assert [body["revision"] for _, body in calls] == [1, 2]
    assert "operationKey" not in args["payload"]


async def test_manual_record_identity_is_metric_date_not_value_or_revision(project_transport):
    runtime, team, binding, _, calls = project_transport
    args = {
        "swarmId": team["id"],
        "operation": "record",
        "payload": {"revision": 1, "metricId": "users", "date": "2026-11-07", "value": 0},
    }
    for changes in (
        {},
        {"revision": 3, "value": 4},
        {"metricId": "downloads"},
        {"date": "2026-11-06"},
    ):
        await invoke(
            runtime,
            binding,
            "swarm_project_update",
            {**args, "payload": {**args["payload"], **changes}},
        )
    keys = [body["operationKey"] for _, body in calls]
    assert keys[0] == keys[1] and len(set(keys)) == 3
    assert calls[0][1]["value"] == 0


async def test_connector_retains_its_original_batch_without_an_extra_key(project_transport):
    runtime, team, binding, _, calls = project_transport
    payload = {"revision": 1, "batch": {"id": "e" * 32, "values": []}}
    result = await invoke(
        runtime,
        binding,
        "swarm_project_update",
        {"swarmId": team["id"], "operation": "record", "payload": payload},
    )
    assert calls[-1][1] == payload
    assert result["connectorBatchReceipt"]["id"] == payload["batch"]["id"]
    assert result["connectorBatchReceipt"]["observationIds"] == ["actual-observation"]
    assert "outputExternalized" not in result


@pytest.mark.parametrize("operation", ["record", "review"])
async def test_model_cannot_choose_its_own_project_operation_identity(project_transport, operation):
    runtime, team, binding, _, calls = project_transport
    with pytest.raises(DomainError, match="SWARM_COORDINATION_OPERATION_KEY_RESERVED"):
        await invoke(
            runtime,
            binding,
            "swarm_project_update",
            {"swarmId": team["id"], "operation": operation, "payload": {"operationKey": "bypass"}},
        )
    assert not calls


async def test_coordinator_memory_is_one_append_and_preserves_actual_receipt(project_transport):
    runtime, team, binding, batch_id, calls = project_transport
    args = {"swarmId": team["id"], "content": "Only the new knowledge", "expectedSha256": "a" * 64}
    result = await invoke(runtime, binding, "swarm_memory_write", args)
    again = await invoke(
        runtime,
        {**binding, "toolCallId": "fresh-call"},
        "swarm_memory_write",
        {**args, "expectedSha256": "b" * 64},
    )
    assert result["operationReceipt"] == again["operationReceipt"]
    assert result["sha256"] == digest("Original knowledge")
    assert "content" not in result and "projectGuidance" not in result
    assert [body["operationKey"] for _, body in calls] == [
        "coordination:" + batch_id + ":memory"
    ] * 2
    assert all(body["mode"] == "append" and body["content"] == args["content"] for _, body in calls)


async def test_old_lease_does_not_reach_project_write_transport(project_transport):
    runtime, team, binding, _, calls = project_transport
    with pytest.raises(DomainError, match="SWARM_COORDINATION_NOT_CURRENT"):
        await invoke(
            runtime,
            {**binding, "leaseEpoch": binding["leaseEpoch"] - 1},
            "swarm_memory_write",
            {"swarmId": team["id"], "content": "new", "expectedSha256": "a" * 64},
        )
    assert not calls


async def test_plain_main_memory_keeps_original_replace_body(delegated_team, monkeypatch):
    runtime, _, team, _, turn, _, _ = delegated_team
    calls = []

    async def execute(argv, **kwargs):
        body = (
            json.loads(kwargs["input_data"])
            if kwargs.get("input_data")
            else {"content": "Original knowledge"}
        )
        if kwargs.get("input_data"):
            calls.append(body)
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {
                    "data": {
                        "projectFiles": {
                            "teamMemory": body["content"],
                            "teamMemorySha256": digest(body["content"]),
                        }
                    }
                }
            ),
        }

    monkeypatch.setattr("roami_agent.storage.swarm_memory.execute", execute)
    args = {"swarmId": team["id"], "content": "Full authorized content", "expectedSha256": "a" * 64}
    await invoke(
        runtime,
        {
            "owner": "alice",
            "conversation": team["mainConversationId"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
            "toolCallId": "ordinary",
        },
        "swarm_memory_write",
        args,
    )
    assert calls == [{"content": args["content"], "expectedSha256": args["expectedSha256"]}]


async def test_actual_large_project_response_is_readable_only_after_its_host_receipt(
    coordinated_tools,
):
    from dataclasses import replace

    from roami_agent.protocol.serialization import encoded

    runtime, team, _, _, _, binding = coordinated_tools
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    large = {"actualProjectValue": "original-project-content " * 7000}
    original = runtime.tools.registry["swarm_project_context"]

    async def project(args, supplied):
        return large

    runtime.tools.registry[original.name] = replace(original, handler=project)
    call = {
        "id": "project-context",
        "function": {
            "name": "swarm_project_context",
            "arguments": json.dumps({"swarmId": team["id"]}),
        },
    }
    result = await runtime.gateway.invoke(turn, mid, call, "main", binding)
    assert result["outputExternalized"] and result["artifactRefs"]
    aid = result["artifactRefs"][0]["id"]
    page = await invoke(
        runtime, binding, "read", {"path": "artifact://" + aid, "offset": 0, "limit": 8000}
    )
    assert page["text"] == encoded(large)[:8000] and page["hasMore"]
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tool_calls SET state='failed' WHERE turn_id=? AND tool_name='swarm_project_context'",
            (turn["id"],),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "read", {"path": "artifact://" + aid})
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tool_calls SET state='succeeded' WHERE turn_id=? AND tool_name='swarm_project_context'",
            (turn["id"],),
        ),
        write=True,
    )
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,created_ms,reason) SELECT 'alice',result_message_id,1,'user' FROM tool_calls WHERE turn_id=? AND tool_name='swarm_project_context'",
            (turn["id"],),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await invoke(runtime, binding, "read", {"path": "artifact://" + aid})


async def test_tool_result_metadata_without_a_successful_current_call_is_not_authority(
    coordinated_tools,
):
    runtime, _, _, _, _, binding = coordinated_tools
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    artifact = await runtime.artifacts.put(
        "alice",
        b"unrecorded",
        mime_type="application/json",
        name="tool-result.json",
        message_id=mid,
        metadata={"source": "tool_result", "toolName": "swarm_project_context"},
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "read", {"path": "artifact://" + artifact["id"]})


@pytest.mark.parametrize(
    "change",
    [
        {"key": "different-batch"},
        {"kind": "observation"},
        {"requestSha256": "z" * 64},
        {"requestSha256": ""},
        {"reviewId": ""},
        {"recordedAt": None},
    ],
)
def test_wrong_project_receipt_is_not_success(change):
    from roami_agent.tools.swarm_coordination_writes import project_receipt

    receipt = {
        "key": "original",
        "kind": "review",
        "reviewId": "actual-review",
        "recordedAt": "2026-11-07T00:00:00Z",
        "requestSha256": "a" * 64,
        **change,
    }
    with pytest.raises(DomainError, match="SWARM_PROJECT_RECEIPT_UNAVAILABLE"):
        project_receipt(
            {"revision": 2, "projectFiles": {"operationReceipt": receipt}},
            {"kind": "review", "key": "original"},
        )


async def test_gateway_records_the_same_host_write_identity_it_executes(project_transport):
    runtime, team, binding, batch_id, calls = project_transport
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    args = {
        "swarmId": team["id"],
        "operation": "review",
        "payload": {"revision": 1, "summary": "Actual evidence"},
    }
    call = {
        "id": "review-current",
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {"argv": ["roami", "swarm", "project", "update", "--input", json.dumps(args)]}
            ),
        },
    }
    result = await runtime.gateway.invoke(turn, mid, call, "main", binding)
    assert result["operationReceipt"]["key"] == "coordination:" + batch_id + ":review"
    stored = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT arguments_json,state FROM tool_calls WHERE turn_id=? AND tool_name='swarm_project_update'",
            (turn["id"],),
        )
    )
    assert stored["state"] == "succeeded"
    assert json.loads(stored["arguments_json"])["payload"] == calls[-1][1]


@pytest.mark.parametrize(
    "previous_state,previous_error",
    [
        ("succeeded", None),
        ("unknown", None),
        ("cancelled", None),
        ("failed", None),
        ("failed", "OKR_CONFLICT"),
        ("failed", "OKR_FILES_PENDING"),
    ],
)
async def test_gateway_connector_replay_pins_original_batch_and_revision(
    project_transport, previous_state, previous_error
):
    runtime, team, binding, _, calls = project_transport
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    payload = {
        "revision": 1,
        "batch": {
            "id": "a" * 32,
            "connectorId": "github-data",
            "sourceIdentity": "public-repo",
            "date": "2026-11-07",
            "windowStart": "2026-11-07T00:00:00Z",
            "windowEnd": "2026-11-07T00:00:00Z",
            "values": [],
        },
    }

    async def execute(key, body):
        args = {"swarmId": team["id"], "operation": "record", "payload": body}
        return await runtime.gateway.invoke(
            turn,
            mid,
            {
                "id": key,
                "function": {"name": "swarm_project_update", "arguments": json.dumps(args)},
            },
            "main",
            {**binding, "toolCallId": key},
        )

    original = await execute("original-batch", payload)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tool_calls SET state=? WHERE turn_id=? AND tool_name='swarm_project_update'",
            (previous_state, turn["id"]),
        ),
        write=True,
    )
    if previous_error:
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=? WHERE id=(SELECT result_message_id FROM tool_calls WHERE turn_id=? AND tool_name='swarm_project_update' ORDER BY rowid LIMIT 1)",
                (json.dumps({"text": json.dumps({"error": previous_error})}), turn["id"]),
            ),
            write=True,
        )
    fresh = {**payload, "revision": 8, "batch": {**payload["batch"], "id": "b" * 32}}
    replay = await execute("fresh-model-call", fresh)
    assert replay["connectorBatchReceipt"] == original["connectorBatchReceipt"]
    assert [body for _, body in calls] == [payload, payload]
    changed = await execute(
        "changed-candidate", {**fresh, "batch": {**fresh["batch"], "values": [{"value": 8}]}}
    )
    assert changed["error"] == "SWARM_COORDINATION_CONNECTOR_CHANGED" and len(calls) == 2
    later = {
        **payload,
        "batch": {
            **payload["batch"],
            "id": "c" * 32,
            "windowStart": "2026-11-07T01:00:00Z",
            "windowEnd": "2026-11-07T01:00:00Z",
        },
    }
    result = await execute("later-snapshot", later)
    assert result["connectorBatchReceipt"]["id"] == "c" * 32


@pytest.mark.parametrize("name", ["swarm_memory_write", "swarm_project_update"])
async def test_old_project_host_is_rejected_before_any_keyed_write(
    project_transport, monkeypatch, name
):
    from roami_agent.storage import swarm_memory

    runtime, team, binding, _, calls = project_transport
    original = swarm_memory.execute

    async def old_host(argv, **kwargs):
        response = await original(argv, **kwargs)
        decoded = json.loads(response["stdout"])
        decoded["data"]["projectFiles"].pop("operationReceiptsSupported", None)
        return {**response, "stdout": json.dumps(decoded)}

    monkeypatch.setattr(swarm_memory, "execute", old_host)
    args = (
        {
            "swarmId": team["id"],
            "content": "New knowledge",
            "expectedSha256": digest("Original knowledge"),
        }
        if name == "swarm_memory_write"
        else {
            "swarmId": team["id"],
            "operation": "review",
            "payload": {"revision": 1, "summary": "Actual evidence", "actions": "Continue"},
        }
    )
    with pytest.raises(DomainError, match="SWARM_PROJECT_WRITE_RECEIPTS_UNAVAILABLE"):
        await invoke(runtime, binding, name, args)
    assert calls == []
