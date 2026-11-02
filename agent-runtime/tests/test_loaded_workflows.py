"""Explicit workflow reads retain scoped execution guidance, not extra authority."""

import base64
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import request_tokens
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message

FIXTURE = Path(__file__).resolve().parent / "fixtures/workflow-reads.json"
MARKER = "Optional workflow instructions read for this request: "
SELECTION = "Optional workflow selection for this request: "


async def install(runtime):
    data = json.loads(FIXTURE.read_text())
    await runtime.capability_imports.save(
        "local",
        "skills",
        {
            "name": data["name"],
            "description": data["description"],
            "text": data["text"],
            "files": {data["reference"]: base64.b64encode(data["referenceText"].encode()).decode()},
        },
    )
    return data


def read_messages(runtime, data, *, reference="", function="read"):
    value = runtime.tools.skills[data["name"]]
    content = value["references"][reference] if reference else value
    receipt = {key: content[key] for key in ["text", "version"]}
    if reference:
        receipt["skillVersion"] = value["version"]
    path = "skill://" + data["name"] + ("/" + reference if reference else "")
    args = (
        {"path": path}
        if function == "read"
        else {"name": data["name"], **({"reference": reference} if reference else {})}
    )
    return [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "observed-read",
                    "function": {"name": function, "arguments": json.dumps(args)},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "observed-read", "content": json.dumps(receipt)},
    ]


@pytest.mark.parametrize("function", ["read", "skill_read"])
async def test_native_loop_marks_only_workflows_actually_read(store, tmp_path, function):
    data = json.loads(FIXTURE.read_text())

    class Worker:
        model = "workflow-read-contract"

        def __init__(self):
            self.prompts = []

        async def stream(self, messages, tools):
            self.prompts.append(copy.deepcopy(messages))
            phase = len(self.prompts) - 1
            if phase < 2:
                reference = data["reference"] if phase else ""
                path = "skill://" + data["name"] + ("/" + reference if reference else "")
                args = (
                    {"path": path}
                    if function == "read"
                    else {"name": data["name"], **({"reference": reference} if reference else {})}
                )
                yield ModelEvent(
                    "tool",
                    {
                        "id": "read-" + str(phase),
                        "function": {"name": function, "arguments": json.dumps(args)},
                    },
                )
            else:
                yield ModelEvent(
                    "text",
                    "Read the workflow instructions and field reference. No files were changed.",
                )

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "workflow-contract", "directory": str(tmp_path)}

    worker = Worker()
    settings = Settings(
        main_instructions="Persisted coordinator policy",
        worker_instructions="Persisted worker policy",
    )
    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=worker,
        memory_model=ConversationModel(),
        settings=settings,
    )
    await install(runtime)
    catalog = runtime.tools.catalog("worker")
    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Read the installed station workflow and its field reference; report what was read without changing files.",
            key="workflow-contract",
            target={"kind": "new_session", "directory": str(tmp_path)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE trigger_kind='completion' AND state='completed'"
            ),
        )
        assert len(worker.prompts) == 3
        assert not any(
            m.get("role") == "system" and m.get("content", "").startswith(MARKER)
            for m in worker.prompts[0]
        )
        initial = [
            m["content"]
            for m in worker.prompts[0]
            if m.get("role") == "system" and m.get("content", "").startswith(SELECTION)
        ]
        assert len(initial) == 1 and data["description"] in initial[0]
        assert data["text"] not in initial[0] and data["referenceText"] not in initial[0]
        for index, prompt in enumerate(worker.prompts[1:], start=1):
            assert not any(
                m.get("role") == "system" and m.get("content", "").startswith(SELECTION)
                for m in prompt
            )
            cues = [
                m["content"]
                for m in prompt
                if m.get("role") == "system" and m.get("content", "").startswith(MARKER)
            ]
            assert len(cues) == 1
            cue = cues[0]
            assert "skill://" + data["name"] in cue
            assert runtime.tools.skills[data["name"]]["version"] in cue
            assert (data["reference"] in cue) == (index == 2)
            assert data["text"] not in cue and data["referenceText"] not in cue
            assert (
                sum(
                    data["text"] in m.get("content", "")
                    for m in prompt
                    if isinstance(m.get("content"), str)
                )
                == 1
            )
            assert "does not add tasks or grant authorization" in cue
        assert runtime.tools.catalog("worker") == catalog
        assert settings.main_instructions == "Persisted coordinator policy"
        assert settings.worker_instructions == "Persisted worker policy"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "change",
    [
        "wrong_body",
        "wrong_version",
        "tool_error",
        "missing_call",
        "bash",
        "file",
        "user_result",
        "invalid_json",
        "null_calls",
        "bad_id",
        "bad_name",
    ],
)
async def test_untrusted_or_incomplete_reads_do_not_activate_workflows(store, change):
    runtime = Runtime(store, ConversationModel())
    data = await install(runtime)
    messages = read_messages(runtime, data)
    if change in {"wrong_body", "wrong_version", "tool_error"}:
        receipt = json.loads(messages[1]["content"])
        receipt[
            {"wrong_body": "text", "wrong_version": "version", "tool_error": "error"}[change]
        ] = "untrusted"
        messages[1]["content"] = json.dumps(receipt)
    elif change == "missing_call":
        messages = messages[1:]
    elif change == "bash":
        messages[0]["tool_calls"][0]["function"]["name"] = "bash"
    elif change == "file":
        messages[0]["tool_calls"][0]["function"]["arguments"] = json.dumps(
            {"path": "instructions.txt"}
        )
    elif change == "user_result":
        messages[1]["role"] = "user"
    elif change == "invalid_json":
        messages[1]["content"] = "{"
    elif change == "null_calls":
        messages[0]["tool_calls"] = None
    elif change == "bad_id":
        messages[1]["tool_call_id"] = []
    elif change == "bad_name":
        messages[0]["tool_calls"][0]["function"]["name"] = []
    assert runtime.tools.loaded_workflow_metadata(messages) == []


@pytest.mark.parametrize(
    "change", ["skill_disabled", "read_disabled", "legacy_disabled", "replaced", "removed"]
)
async def test_current_registry_rejects_revoked_or_old_reads(store, change):
    runtime = Runtime(store, ConversationModel())
    data = await install(runtime)
    messages = read_messages(runtime, data)
    assert runtime.tools.loaded_workflow_metadata(messages)
    if change == "skill_disabled":
        runtime.tools.disabled_skills.add(data["name"])
    elif change in {"read_disabled", "legacy_disabled"}:
        runtime.tools.disabled_tools.add("read" if change == "read_disabled" else "skill_read")
    elif change == "replaced":
        runtime.tools.skills[data["name"]]["version"] = "new-version"
    else:
        runtime.tools.skills.pop(data["name"])
    assert runtime.tools.loaded_workflow_metadata(messages) == []


async def test_references_are_exact_and_duplicate_reads_do_not_repeat_the_cue(store):
    runtime = Runtime(store, ConversationModel())
    data = await install(runtime)
    messages = read_messages(runtime, data, reference=data["reference"])
    selected = runtime.tools.loaded_workflow_metadata(messages * 2)
    assert len(selected) == 1 and selected[0]["location"].endswith(data["reference"])
    assert "referenceVersion" in selected[0]
    receipt = json.loads(messages[1]["content"])
    receipt["skillVersion"] = "old-parent-version"
    messages[1]["content"] = json.dumps(receipt)
    assert runtime.tools.loaded_workflow_metadata(messages) == []


@pytest.mark.parametrize("boundary", ["new_request", "forgotten", "deleted"])
async def test_context_projects_only_visible_current_reads_and_counts_the_cue(store, boundary):
    runtime = Runtime(store, ConversationModel())
    data = await install(runtime)
    conversation = await runtime.conversations.create("alice")
    accepted = await runtime.conversations.accept(
        "alice", conversation["id"], "first", "Read the workflow"
    )
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (accepted["turnId"],)), owner_id="alice"
        )
    )
    turn["executionRunId"] = "workflow-attempt"
    catalog = runtime.tools.catalog("worker")
    initial, _ = await runtime.loop.context.build(
        turn, runtime.settings.worker_instructions, catalog, None
    )
    frames = read_messages(runtime, data)
    value = await runtime.tools.invoke(frames[0]["tool_calls"][0], "worker", {"owner": "alice"})

    def append(db):
        message(
            db,
            conversation["id"],
            turn["branch_id"],
            "assistant",
            {"text": "", "tool_calls": frames[0]["tool_calls"]},
            turn_id=turn["id"],
        )
        return message(
            db,
            conversation["id"],
            turn["branch_id"],
            "tool",
            {"text": json.dumps(value), "tool_call_id": "observed-read"},
            turn_id=turn["id"],
        )

    mid = await store.call(append, write=True)
    plan, prompt = await runtime.loop.context.build(
        turn, runtime.settings.worker_instructions, catalog, None
    )
    assert len(plan["loadedWorkflows"]) == 1
    assert plan["estimatedTokens"] >= request_tokens(prompt, catalog)
    assert plan["requestBasis"] == initial["requestBasis"]
    before = await runtime.conversations.messages("alice", conversation["id"])
    repeated, same = await runtime.loop.context.build(
        turn, runtime.settings.worker_instructions, catalog, None
    )
    assert same == prompt and repeated["estimatedTokens"] == plan["estimatedTokens"]
    assert await runtime.conversations.messages("alice", conversation["id"]) == before
    if boundary == "new_request":
        await store.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
        other = await runtime.conversations.accept(
            "alice", conversation["id"], "second", "An independent request"
        )
        turn = await store.call(
            lambda db: dict(
                row(db, "SELECT * FROM turns WHERE id=?", (other["turnId"],)), owner_id="alice"
            )
        )
        turn["executionRunId"] = "another-attempt"
    elif boundary == "forgotten":
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,'test-forget',1)",
                ("alice", mid),
            ),
            write=True,
        )
    else:
        await store.call(
            lambda db: db.execute("UPDATE messages SET deleted_ms=1 WHERE id=?", (mid,)), write=True
        )
    after, projected = await runtime.loop.context.build(
        turn, runtime.settings.worker_instructions, catalog, None
    )
    assert "loadedWorkflows" not in after
    assert not any(m["role"] == "system" and m["content"].startswith(MARKER) for m in projected)
