"""Review contracts reject guesses before node writes and preserve bound saved receipts."""

import json
import shlex

import pytest
from test_project_okr_conversations import create_goal
from test_project_okr_conversations import project_runtime as project_runtime_fixture
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke

from roami_agent.protocol.errors import DomainError, ProjectReviewInputError
from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row
from roami_agent.storage.swarm_memory import digest
from roami_agent.tools.project_review import checked_review, review_payload, review_receipt

project_runtime = project_runtime_fixture
coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


def saved(pid, payload, *, revision=2):
    review = {
        "id": "actual-review",
        "summary": payload["summary"],
        "actions": payload.get("actions", ""),
        "date": "2026-11-09T10:00:00Z",
        "evidenceRevision": 1,
    }
    return {
        "projectId": pid,
        "revision": revision,
        "reviews": [review],
        "privateLargeContext": "not needed in this receipt" * 1000,
        "projectFiles": {
            "operationReceiptsSupported": True,
            "operationReceipt": {
                "kind": "review",
                "key": payload["operationKey"],
                "reviewId": review["id"],
                "requestSha256": "a" * 64,
                "recordedAt": "2026-11-09T10:00:00Z",
            },
        },
    }


def args():
    return {
        "revision": 1,
        "summary": "真实记录：测试了断线重连，三次均通过。",
        "actions": "保持原实例，按原计划继续。",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"title": "private", "summary": None},
        {"summary": " "},
        {"summary": 3},
        {"actions": None},
        {"revision": True},
        {"revision": 1.0},
        {"revision": 2**63},
        {"unknown": "private"},
        {"summary": "\ud800"},
    ],
)
def test_exact_review_contract_rejects_missing_wrong_or_unencodable_fields(change):
    with pytest.raises(ProjectReviewInputError):
        checked_review({**args(), **change})


async def test_actual_gateway_returns_public_contract_and_corrected_alias_writes_bound_project(
    project_runtime, monkeypatch
):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    source = await runtime.conversations.accept(
        "alice", cid, "save-review", "保存有真实证据的复盘，不写测试占位。"
    )
    job = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (source["turnId"],))
    )
    turn = await runtime.mailbox.claim(job)
    binding = {
        "owner": "alice",
        "conversation": cid,
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "originMessageId": source["messageId"],
    }
    writes = []

    async def operation(settings, pid, action, payload=None):
        assert pid == "registered"
        if action == "show":
            return {
                "projectId": pid,
                "revision": 1,
                "projectFiles": {"operationReceiptsSupported": True},
            }
        writes.append((pid, action, payload))
        return saved(pid, payload)

    monkeypatch.setattr("roami_agent.tools.project_okr.operation", operation)
    monkeypatch.setattr("roami_agent.tools.project_review.operation", operation)

    async def call(name, body):
        mid = await runtime.journal.start(turn)
        return await runtime.gateway.invoke(
            turn,
            mid,
            {"id": identity(), "function": {"name": name, "arguments": json.dumps(body)}},
            "main",
            binding,
        )

    bad = {"operation": "review", "payload": {"revision": 1, "content": "never-leak-this"}}
    result = await call(
        "bash", {"argv": ["roami", "project", "okr", "update", "--input", json.dumps(bad)]}
    )
    assert result["error"] == "OKR_REVIEW_INPUT_INVALID" and result["executionStarted"] is False
    assert result["expectedInputSchema"]["required"] == ["revision", "summary"]
    assert "never-leak-this" not in json.dumps(result) and not writes
    result = await call(
        "bash",
        {
            "command": shlex.join(
                ["roami", "project", "okr", "review", "--input", json.dumps(args())]
            )
        },
    )
    assert result["projectId"] == "registered" and result["review"]["summary"] == args()["summary"]
    assert "privateLargeContext" not in result and "projectFiles" not in result
    assert writes[0][:2] == ("registered", "review")
    assert result["operationReceipt"]["key"] == writes[0][2]["operationKey"]


async def test_typed_project_review_checks_scope_and_receipt_support_before_writing(
    project_runtime, monkeypatch
):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    binding = {"owner": "alice", "conversation": cid, "role": "main", "turnId": "original-turn"}
    calls = []

    async def operation(settings, pid, action, payload=None):
        calls.append(action)
        return {"projectId": pid, "projectFiles": {}}

    monkeypatch.setattr("roami_agent.tools.project_review.operation", operation)
    tool = runtime.tools.registry["project_okr_review"]
    with pytest.raises(DomainError, match="PROJECT_REVIEW_RECEIPTS_UNAVAILABLE"):
        await tool.handler(args(), binding)
    assert calls == ["show"]
    for changed in [
        {"owner": "bob"},
        {"role": "worker"},
        {"taskId": "worker-task"},
        {"conversation": (await runtime.conversations.main("alice"))["id"]},
    ]:
        with pytest.raises(DomainError):
            await tool.handler(args(), {**binding, **changed})
    assert calls == ["show"]


def test_key_survives_new_calls_fresh_cas_and_omitted_empty_actions():
    first = review_payload({**args(), "actions": ""}, {"turnId": "original", "toolCallId": "one"})
    changed = {k: v for k, v in args().items() if k != "actions"}
    second = review_payload({**changed, "revision": 9}, {"turnId": "original", "toolCallId": "two"})
    assert first["operationKey"] == second["operationKey"]
    assert (
        review_payload(
            {**args(), "summary": "更改文字不能制造第二条记录。"}, {"turnId": "original"}
        )["operationKey"]
        == first["operationKey"]
    )
    assert first["summary"] == args()["summary"]
    with pytest.raises(DomainError, match="PROJECT_REVIEW_TURN_REQUIRED"):
        review_payload(args(), {})


@pytest.mark.parametrize(
    "damage", ["project", "key", "kind", "missing_review", "content", "files", "reviews"]
)
def test_only_matching_saved_review_is_reported(damage):
    payload = review_payload(args(), {"turnId": "original"})
    value = saved("project-a", payload)
    if damage == "project":
        value["projectId"] = "project-b"
    elif damage in {"key", "kind"}:
        value["projectFiles"]["operationReceipt"][damage] = "other"
    elif damage == "missing_review":
        value["reviews"] = []
    elif damage == "content":
        value["reviews"][0]["summary"] = "other"
    elif damage == "files":
        value["projectFiles"] = None
    else:
        value["reviews"] = None
    with pytest.raises(DomainError):
        review_receipt(value, "project-a", payload)


async def test_coordination_review_reuses_existing_batch_identity_and_minimal_receipt(
    coordinated_tools, monkeypatch
):
    runtime, team, _, _, _, binding = coordinated_tools
    writes = []

    async def execute(argv, **kwargs):
        payload = json.loads(kwargs["input_data"]) if kwargs.get("input_data") else None
        if payload:
            writes.append(payload)
            data = saved("project-a", payload)
        else:
            data = {
                "projectId": "project-a",
                "projectFiles": {
                    "operationReceiptsSupported": True,
                    "teamMemory": "Original knowledge",
                    "teamMemorySha256": digest("Original knowledge"),
                },
            }
        return {"exitCode": 0, "stdout": json.dumps({"data": data})}

    monkeypatch.setattr("roami_agent.storage.swarm_memory.execute", execute)
    batch = await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (binding["turnId"],)
        )
    )
    body = {"swarmId": team["id"], **args()}
    result = await invoke(
        runtime,
        binding,
        "bash",
        {"argv": ["roami", "swarm", "project", "review", "--input", json.dumps(body)]},
    )
    expected = "coordination:" + batch["id"] + ":review"
    assert result["operationReceipt"]["key"] == expected and "outputExternalized" not in result
    await invoke(
        runtime, {**binding, "toolCallId": "new"}, "swarm_project_review", {**body, "revision": 9}
    )
    assert [p["operationKey"] for p in writes] == [expected, expected]
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "swarm_project_review", {**body, "swarmId": "other"})
    assert len(writes) == 2


async def test_legacy_swarm_review_guesses_are_rejected_before_node_write(
    coordinated_tools, monkeypatch
):
    runtime, team, _, _, _, binding = coordinated_tools
    writes = []

    async def execute(argv, **kwargs):
        if kwargs.get("input_data"):
            writes.append(kwargs["input_data"])
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {
                    "data": {
                        "projectId": "project-a",
                        "projectFiles": {
                            "operationReceiptsSupported": True,
                            "teamMemory": "Original knowledge",
                            "teamMemorySha256": digest("Original knowledge"),
                        },
                    }
                }
            ),
        }

    monkeypatch.setattr("roami_agent.storage.swarm_memory.execute", execute)
    with pytest.raises(ProjectReviewInputError):
        await invoke(
            runtime,
            binding,
            "swarm_project_update",
            {
                "swarmId": team["id"],
                "operation": "review",
                "payload": {"revision": 1, "title": "private"},
            },
        )
    assert not writes
