"""Long workflows retain receipts and full evidence without arbitrary execution ceilings."""

import hashlib
import json
import sys

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tool_arguments import ToolArgumentsError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.server.configuration import Settings
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import row
from roami_agent.tools.registry import Tools
from roami_agent.tools.shell import register_shell


def call(name, arguments):
    return {"id": "fixture", "function": {"name": name, "arguments": json.dumps(arguments)}}


async def test_shell_finishes_after_more_than_two_megabytes_and_preserves_exit_status(
    store, tmp_path
):
    artifacts = ArtifactStore(store)
    registry = Tools(artifacts)
    register_shell(registry, Settings(shell_roots=(tmp_path,)), artifacts)
    try:
        size = 3 * 1024 * 1024 + 17
        result = await registry.invoke(
            call(
                "shell",
                {
                    "cwd": str(tmp_path),
                    "argv": [
                        sys.executable,
                        "-c",
                        f"import os; from pathlib import Path; os.write(1,b'x'*{size}); Path('finished').write_text('done'); raise SystemExit(7)",
                    ],
                },
            ),
            "worker",
            {"owner": "alice"},
        )
        assert result["exitCode"] == 7 and (tmp_path / "finished").read_text() == "done"
        assert len(result["stdout"].encode()) <= 4000
        reference, tail = await artifacts.read_page(
            "alice", result["artifactRefs"][0]["id"], size - 17, 17
        )
        assert reference["sizeBytes"] == size and tail == b"x" * 17
        assert not list(store.data_root.glob(".shell-output-*"))
    finally:
        await artifacts.close()


async def test_streamed_artifacts_exceed_old_64_mib_limit_without_full_file_reads(store, tmp_path):
    artifacts = ArtifactStore(store)
    source = tmp_path / "large.bin"
    size = 65 * 1024 * 1024 + 4
    with source.open("wb") as file:
        file.truncate(size - 4)
        file.seek(size - 4)
        file.write(b"tail")
    try:
        reference = await artifacts.put_file("alice", source, mime_type="application/octet-stream")
        verified, tail = await artifacts.read_page("alice", reference["id"], size - 4, 4)
        assert verified == reference and reference["sizeBytes"] == size and tail == b"tail"
        digest = hashlib.sha256()
        with source.open("rb") as file:
            while chunk := file.read(65536):
                digest.update(chunk)
        assert reference["sha256"] == digest.hexdigest()
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await artifacts.read_page("bob", reference["id"], 0, 4)
    finally:
        await artifacts.close()


async def test_large_tool_result_runs_once_and_keeps_full_json_with_a_small_receipt(store):
    artifacts = ArtifactStore(store)
    registry = Tools(artifacts)
    effects = []
    value = {"state": "succeeded", "exitCode": 0, "entries": ["evidence" * 10000] * 3}

    async def write(arguments, binding):
        effects.append("write")
        return value

    registry.add(Tool("large_write", "Persist evidence", object_schema({}), write, effect="write"))
    try:
        result = await registry.invoke(call("large_write", {}), "worker", {"owner": "alice"})
        assert effects == ["write"] and result["state"] == "succeeded" and result["exitCode"] == 0
        assert result["outputExternalized"] and len(json.dumps(result)) < 8000
        _, body = await artifacts.read("alice", result["artifactRefs"][0]["id"])
        assert json.loads(body) == value
    finally:
        await artifacts.close()


async def test_more_than_sixteen_tools_and_long_model_text_are_not_rejected(store):
    effects = []
    text = "full requested response " * 5000

    class Model:
        model = "wide-tool-batch"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", text)
            else:
                for index in range(24):
                    yield ModelEvent(
                        "tool", {"id": str(index), "function": {"name": "probe", "arguments": "{}"}}
                    )

    async def probe(arguments, binding):
        effects.append(binding["toolCallId"])
        return {"observed": True}

    runtime = Runtime(store, Model())
    runtime.tools.directory = None
    runtime.tools.add(Tool("probe", "Observe", object_schema({}), probe, main=True))
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.conversations.accept(
            "alice", conversation["id"], "batch", "Run all observations and return full text"
        )
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE aggregate_id=? AND kind='turn.run'",
                (receipt["turnId"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        assert await runtime.loop.run(turn, "main") == text
        assert len(effects) == len(set(effects)) == 24
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        assert messages[-1]["content"]["text"] == text
    finally:
        await runtime.close()


async def test_provider_accepts_large_arguments_and_wide_tool_indices():
    arguments = json.dumps({"content": "x" * 120000})
    calls = [
        {
            "index": index,
            "id": str(index),
            "type": "function",
            "function": {"name": "observe", "arguments": arguments if index == 23 else "{}"},
        }
        for index in range(24)
    ]

    async def respond(request):
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {"choices": [{"delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}]}
            )
            + "\n\ndata: [DONE]\n\n",
        )

    provider = ChatCompletions(
        "https://fixture.invalid/v1",
        "large-tools",
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        parts = [part async for part in provider.stream([], [])]
        tools = [part.value for part in parts if part.kind == "tool"]
        assert len(tools) == 24 and tools[-1]["function"]["arguments"] == arguments
    finally:
        await provider.close()


async def test_malformed_tool_json_is_corrected_without_execution_or_losing_the_turn(store):
    requests, effects = [], []

    async def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) < 3:
            if len(requests) == 2:
                assert (
                    json.loads(body["messages"][-1]["content"])["error"] == "INVALID_TOOL_ARGUMENTS"
                )
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": str(len(requests)),
                        "function": {
                            "name": "probe",
                            "arguments": '{"value":' if len(requests) == 1 else "{}",
                        },
                    }
                ]
            }
        else:
            assert effects == ["written"]
            delta = {"content": "Recovered without repeating the write"}
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": delta,
                            "finish_reason": "tool_calls" if len(requests) < 3 else "stop",
                        }
                    ]
                }
            )
            + "\n\ndata: [DONE]\n\n",
        )

    provider = ChatCompletions(
        "https://fixture.invalid/v1",
        "repair",
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    runtime = Runtime(store, provider, memory_model=ConversationModel())
    runtime.tools.directory = None

    async def write(arguments, binding):
        effects.append("written")
        return {"state": "succeeded"}

    runtime.tools.add(
        Tool("probe", "Write once", object_schema({}), write, main=True, effect="write")
    )
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.conversations.accept(
            "alice", conversation["id"], "repair", "Write once"
        )
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (receipt["turnId"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        assert await runtime.loop.run(turn, "main") == "Recovered without repeating the write"
        assert len(requests) == 3 and effects == ["written"]
    finally:
        await runtime.close()
        await provider.close()


async def test_task_nesting_and_fanout_are_queued_without_admission_caps(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        parent = await runtime.tasks.create(
            "alice", conversation["id"], "Parent", key="parent", record_intent=True
        )
        for depth in range(6):
            await store.call(
                lambda db, tid=parent["id"]: db.execute(
                    "UPDATE tasks SET state='running' WHERE id=?", (tid,)
                ),
                write=True,
            )
            children = [
                await runtime.tasks.create(
                    "alice",
                    conversation["id"],
                    f"Depth {depth} child {index}",
                    key=f"{depth}-{index}",
                    parent_task_id=parent["id"],
                )
                for index in range(5)
            ]
            assert all(child["state"] == "queued" for child in children)
            parent = children[0]
        assert json.loads(parent["budget_json"])["depth"] == 6
    finally:
        await runtime.close()


async def test_argument_diagnostics_explain_all_schema_errors_without_values(store):
    runtime = Runtime(store, ConversationModel())
    supplied_value = "credential value must stay private"
    try:
        malformed = call(
            "bash",
            {
                "argv": [
                    "roami",
                    "agent",
                    "capability",
                    "call",
                    "task_status",
                    "--input",
                    json.dumps({"extra": supplied_value}),
                ]
            },
        )
        with pytest.raises(ToolArgumentsError) as failure:
            runtime.tools.validate(malformed, "main")
        issue = failure.value.issues[0]
        assert issue["rule"] == "additionalProperties" and issue["allowedFields"] == [
            "taskId",
            "includeResult",
        ]
        assert supplied_value not in json.dumps(failure.value.issues)
        bad = call(
            "delegate",
            {
                "requestComplete": False,
                "goal": "Work",
                "routing": {
                    "complexity": "complex",
                    "complexityBasis": {"burden": supplied_value},
                    "routingExplanation": "Requires research",
                    "unrelated": supplied_value,
                },
            },
        )
        with pytest.raises(ToolArgumentsError) as failure:
            runtime.tools.validate(bad, "main")
        assert any(
            issue.get("missingFields") == ["explicitExecutor"] for issue in failure.value.issues
        )
        assert any(issue["rule"] == "additionalProperties" for issue in failure.value.issues)
        assert supplied_value not in json.dumps(failure.value.issues)
    finally:
        await runtime.close()


def test_zero_limits_are_unlimited_and_explicit_long_timeouts_remain_valid(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text(
        "[runtime]\ntimeout_seconds=0\nmax_depth=0\n[artifacts]\nmax_bytes=0\n[proactive]\ntimeout_seconds=0\n[briefs]\ntimeout_seconds=600\n"
    )
    settings = Settings.load(path)
    assert settings.timeout_for("main") == 0 and settings.max_depth == 0
    assert settings.artifact_max_bytes == 0 and settings.proactive_timeout_seconds == 0
    assert settings.brief_timeout_seconds == 600


@pytest.mark.parametrize("size", [8, 80000])
async def test_http_tools_keep_large_responses_without_timeout_or_output_failure(
    store, tmp_path, monkeypatch, size
):
    from roami_agent.tools.worker_catalog import add_worker_tools

    artifacts = ArtifactStore(store)
    registry = Tools(artifacts)
    client = httpx.AsyncClient
    body = b"x" * size
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(200, content=body, headers={"content-type": "text/plain"})

    def connect(**options):
        assert options["timeout"].read is None and options["timeout"].connect == 10
        return client(transport=httpx.MockTransport(handle), **options)

    monkeypatch.setattr("roami_agent.tools.worker_catalog.httpx.AsyncClient", connect)
    add_worker_tools(
        registry,
        Settings(http_tools={"source": {"url": "https://fixture.invalid/data"}}),
        artifacts,
    )
    try:
        result = await registry.invoke(call("http_source", {}), "worker", {"owner": "alice"})
        assert result["status"] == 200 and len(calls) == 1
        if size > 64000:
            _, retained = await artifacts.read("alice", result["artifactRefs"][0]["id"])
            assert retained == body and len(result["body"]) == 4000
        else:
            assert result == {"status": 200, "body": body.decode()}
    finally:
        await artifacts.close()


async def test_mcp_more_than_32_binary_parts_are_all_retained(store):
    import base64

    from mcp import types

    from roami_agent.tools.mcp_results import MCPResults

    artifacts = ArtifactStore(store)
    try:
        answer = types.CallToolResult(
            content=[
                types.ImageContent(
                    type="image", data=base64.b64encode(b"evidence").decode(), mimeType="image/png"
                )
                for _ in range(40)
            ]
        )
        result = await MCPResults(artifacts).project(answer, {"owner": "alice"}, "images", "read")
        assert len(result["artifactRefs"]) == 40
        assert len({item["id"] for item in result["artifactRefs"]}) == 40
        assert {item["metadata"]["part"] for item in result["artifactRefs"]} == set(range(40))
    finally:
        await artifacts.close()
