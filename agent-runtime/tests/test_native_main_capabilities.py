"""Native Main capabilities use the original turn, gateway and immutable provider."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from test_project_main_execution import setup_main

from roami_agent.context.native_prompt import INLINE_LIMIT, PAGE_BYTES, READ_CAPABILITY
from roami_agent.context.swarm_coordination import CURRENT_BATCH_PREFIX
from roami_agent.conversation.main_execution import main_binding
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.providers.native_main import NativeMain
from roami_agent.server.http import create_app
from roami_agent.storage.database import row

pytest_plugins = ["test_project_main_wakeup"]


@pytest.fixture
async def native_main(wake_runtime, monkeypatch):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    accepted = await runtime.conversations.accept(
        "alice", main["id"], "native-work", "Coordinate the original project team"
    )

    def running(db):
        db.execute(
            "UPDATE turns SET state='running',lease_epoch=1 WHERE id=?", (accepted["turnId"],)
        )
        return row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (accepted["turnId"],),
        )

    turn = await runtime.db.call(running, write=True)
    await runtime.journal.start(turn)
    binding = await runtime.db.call(lambda db: main_binding(db, "alice", main["id"]))
    brief = await runtime.main_capabilities.brief(binding, turn)
    files = list((runtime.db.data_root / "agents/capability-contexts").glob("*.json"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    context = json.loads(files[0].read_text())
    assert context["signature"] not in brief and str(files[0]) in brief
    assert "taskId" not in context and "runId" not in context
    return runtime, main, turn, context


def request(context, args=None, key="one"):
    return {"executionContext": context, "requestId": key, "arguments": args or {}}


async def signed_native_launch(runtime, main, turn, retry_suffix=""):
    binding = await runtime.db.call(lambda db: main_binding(db, "alice", main["id"]))
    key = "project-main:" + turn["id"] + ":" + "a" * 24 + retry_suffix
    await runtime.main_capabilities.brief(binding, {**turn, "native_launch_key": key})
    signed = next(
        context
        for path in (runtime.db.data_root / "agents/capability-contexts").glob("*.json")
        if (context := json.loads(path.read_text())).get("nativeLaunchKey") == key
    )
    return binding, key, signed


async def test_large_coordination_uses_bound_read_only_context_without_changing_launch(native_main):
    runtime, main, turn, original_context = native_main
    binding = await runtime.db.call(lambda db: main_binding(db, "alice", main["id"]))
    binding["binding"] = json.loads(binding.pop("binding_json"))
    messages = [
        {"role": "system", "content": "Current team rules"},
        {"role": "user", "content": "历史证据🙂" * 30000},
        {"role": "system", "content": CURRENT_BATCH_PREFIX + "Frozen original goal and evidence"},
        {"role": "system", "content": "Current resume policy"},
    ]
    key = (
        "project-main:"
        + turn["id"]
        + ":"
        + hashlib.sha256(encoded(messages).encode()).hexdigest()[:24]
    )
    context = None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://testserver",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        route = "/v1/tool-directory/" + READ_CAPABILITY + "/call"

        async def command(sub, *args, spec):
            nonlocal context
            assert (sub, *args) == ("launch", "--file", "-")
            assert spec["key"] == key and spec["preparedFrom"] == binding["launch_key"]
            assert spec["sessionId"] == binding["session_id"] and spec["persistent"]
            assert len(spec["prompt"].encode()) < INLINE_LIMIT
            assert READ_CAPABILITY in spec["prompt"] and "历史证据" not in spec["prompt"]
            context = next(
                signed
                for path in (runtime.db.data_root / "agents/capability-contexts").glob("*.json")
                if (signed := json.loads(path.read_text())).get("nativeLaunchKey") == key
            )
            index = await client.post(route, json=request(context, key="context-index"))
            assert index.status_code == 200
            assert index.json()["data"]["result"] == {
                "messageCount": 4,
                "systemIndices": [0, 2, 3],
                "coordinationIndex": 2,
            }
            for number, message in enumerate(messages):
                offset, parts = 0, []
                while offset is not None:
                    page = await client.post(
                        route, json=request(context, {"index": number, "offset": offset})
                    )
                    assert page.status_code == 200
                    part = page.json()["data"]["result"]
                    assert part["offset"] == offset and 0 < len(part["text"].encode()) <= PAGE_BYTES
                    parts.append(part["text"])
                    offset = part["nextOffset"]
                assert "".join(parts) == encoded(message)
            with pytest.raises(DomainError, match="ACTIVE_MAIN_CONTEXT_REQUIRED"):
                await runtime.main_capabilities.call(READ_CAPABILITY, request(context), "bob")
            with pytest.raises(DomainError, match="NATIVE_PROMPT_CONTEXT_UNAVAILABLE"):
                await runtime.main_capabilities.call(
                    READ_CAPABILITY, request(original_context), "alice"
                )
            invalid = await client.post(route, json=request(context, {"index": True}))
            assert invalid.status_code == 400
            for epoch in (2, 1):
                await runtime.db.call(
                    lambda db, epoch=epoch: db.execute(
                        "UPDATE turns SET lease_epoch=? WHERE id=?", (epoch, turn["id"])
                    ),
                    write=True,
                )
                if epoch == 2:
                    stale = await client.post(route, json=request(context))
                    assert stale.status_code == 409
            return {
                "session": spec["sessionId"],
                "sessionBinding": binding["binding"],
                "result": {
                    "state": "succeeded",
                    "inputStopped": True,
                    "outcomeKnown": True,
                    "summary": "Native answer",
                },
            }

        model = NativeMain(
            binding,
            {**turn, "trigger_kind": "continuation"},
            command,
            capabilities=runtime.main_capabilities,
        )
        assert [event.value async for event in model.stream(messages, [])] == ["Native answer"]
        released = await client.post(route, json=request(context))
        assert released.status_code == 409
        assert not runtime.main_capabilities.prepared_prompts
        calls = await runtime.db.call(
            lambda db: row(
                db, "SELECT count(*) count FROM tool_calls WHERE turn_id=?", (turn["id"],)
            )
        )
        assert calls["count"] == 0


async def group_for(runtime, main, turn):
    runtime.swarms.chat = None
    return await runtime.swarms.create(
        "alice",
        {
            "commandKey": "native-team",
            "name": "Original project team",
            "goal": "Read and verify",
            "mainConversationId": main["id"],
            "target": {"kind": "project", "projectId": "project"},
        },
        binding={"turnId": turn["id"]},
    )


async def test_native_main_uses_actual_registry_gateway_and_original_team(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    payload = request(context, {"swarmId": group["id"]})
    result = await runtime.main_capabilities.call("swarm_status", payload, "alice")
    assert result["state"] == "succeeded" and result["result"]["mainConversationId"] == main["id"]
    assert await runtime.main_capabilities.call("swarm_status", payload, "alice") == result
    calls = await runtime.db.call(
        lambda db: db.execute(
            "SELECT tool_name,state FROM tool_calls WHERE turn_id=?", (turn["id"],)
        ).fetchall()
    )
    assert (
        len(calls) == 1
        and calls[0]["tool_name"] == "swarm_status"
        and calls[0]["state"] == "succeeded"
    )
    with pytest.raises(DomainError, match="CAPABILITY_REQUEST_CONFLICT"):
        await runtime.main_capabilities.call("swarm_memory_read", payload, "alice")


@pytest.mark.parametrize("retry_suffix", ["", ":retry-1"])
async def test_claude_input_uses_signed_registered_capability_launch(
    native_main, monkeypatch, retry_suffix
):
    runtime, main, turn, original_context = native_main
    binding, key, signed = await signed_native_launch(runtime, main, turn, retry_suffix)
    assert "nativeLaunchKey" not in original_context
    with pytest.raises(DomainError, match="ACTIVE_MAIN_CONTEXT_REQUIRED"):
        await runtime.main_capabilities.call(
            "swarm_status", request({**signed, "nativeLaunchKey": key[:-1] + "b"}), "alice"
        )
    cli_proof = {
        "providerId": binding["provider_id"],
        "promptId": "current-native-prompt",
        "requestSha256": "a" * 64,
        "capabilities": [],
        "images": [{"mime": "image/png", "sha256": "b" * 64}],
    }

    async def observed(sub, *args):
        assert (sub, *args[:-1]) == (
            "capability-input",
            "--key",
            key,
            "--capability",
            "check_evidence",
            "--request",
        )
        assert args[-1] in {"current", "wrong-provider"}
        return cli_proof

    monkeypatch.setattr(runtime.main_executions.executor, "command", observed)

    async def input_proof(args, call_binding):
        if args.get("wrongTool"):
            call_binding = {
                **call_binding,
                "nativeCapabilityCall": {
                    **call_binding["nativeCapabilityCall"],
                    "name": "another_tool",
                },
            }
        return await runtime.main_capabilities.capability_input(call_binding)

    runtime.tools.add(
        Tool(
            "check_evidence",
            "Check the input evidence",
            object_schema({"wrongTool": {"type": "boolean"}}),
            input_proof,
            main=True,
            effect="read",
        )
    )
    actual = await runtime.main_capabilities.call(
        "check_evidence", request(signed, key="current"), "alice"
    )
    assert actual["state"] == "succeeded" and actual["result"] == cli_proof
    wrong_tool = await runtime.main_capabilities.call(
        "check_evidence", request(signed, {"wrongTool": True}, "wrong-tool"), "alice"
    )
    assert wrong_tool["state"] == "failed"
    assert wrong_tool["result"]["error"] == "NATIVE_CAPABILITY_INPUT_UNCONFIRMED"
    cli_proof["providerId"] = "another-provider"
    wrong_provider = await runtime.main_capabilities.call(
        "check_evidence", request(signed, key="wrong-provider"), "alice"
    )
    assert wrong_provider["state"] == "failed"
    assert wrong_provider["result"]["error"] == "NATIVE_CAPABILITY_INPUT_UNCONFIRMED"


async def test_native_artifact_view_lives_only_for_the_admitted_turn(native_main, monkeypatch):
    runtime, main, turn, original_context = native_main
    _, _, signed = await signed_native_launch(runtime, main, turn)
    expected = b"image bytes already verified by the artifact store"
    artifact = await runtime.artifacts.put(
        "alice", expected, name="visual.png", mime_type="image/png"
    )

    async def preview(args, binding):
        return {"path": await runtime.main_capabilities.artifact_view(binding, artifact["id"])}

    runtime.tools.add(
        Tool(
            "preview_artifact",
            "Read the visual artifact",
            object_schema({}),
            preview,
            main=True,
            effect="read",
        )
    )
    invalid = await runtime.main_capabilities.call(
        "preview_artifact", request(original_context), "alice"
    )
    assert invalid["state"] == "failed"
    value = await runtime.main_capabilities.call(
        "preview_artifact", request(signed, key="image"), "alice"
    )
    image = Path(value["result"]["path"])
    assert value["state"] == "succeeded"
    assert image.suffix == ".png" and image.is_symlink() and image.read_bytes() == expected
    assert image.parent.stat().st_mode & 0o777 == 0o700
    original_blob = image.resolve()

    async def finished(*args, **kwargs):
        return "done"

    monkeypatch.setattr(runtime, "_run_turn", finished)
    assert await runtime.run_turn({**turn, "lease_epoch": turn["lease_epoch"] + 1}) == "done"
    assert image.is_symlink()
    assert await runtime.run_turn(turn) == "done"
    assert not image.is_symlink() and original_blob.read_bytes() == expected
    left = runtime.main_capabilities.artifact_views.root / "turn-orphan01"
    left.mkdir(mode=0o700)
    (left / "image.png").symlink_to(original_blob)
    runtime.main_capabilities.artifact_views.recover()
    assert not left.exists() and original_blob.read_bytes() == expected


async def test_signed_native_main_can_register_and_plan_without_worker_impersonation(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    registered = await runtime.main_capabilities.call(
        "swarm_members_register",
        request(
            context,
            {
                "swarmId": group["id"],
                "expectedRevision": 1,
                "members": [
                    {"name": "content", "executor": "claude", "duty": "Maintain project content"}
                ],
            },
            "register",
        ),
        "alice",
    )
    assert registered["state"] == "succeeded", registered
    member = registered["result"]["members"][0]
    result = await runtime.main_capabilities.call(
        "swarm_plan",
        request(
            context,
            {
                "swarmId": group["id"],
                "expectedRevision": 2,
                "items": [
                    {
                        "memberId": member["id"],
                        "member": "content",
                        "executor": "claude",
                        "title": "Read source",
                        "goal": "Read and report source facts",
                        "acceptance": "Cite the real source",
                    }
                ],
            },
            "plan",
        ),
        "alice",
    )
    assert result["state"] == "succeeded", result
    current = await runtime.swarms.snapshot("alice", group["id"])
    assert (
        current["mainConversationId"] == main["id"] and current["members"][0]["id"] == member["id"]
    )
    assert current["work"][0]["executor"] == "claude"


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "project",
        "conversation",
        "provider",
        "generation",
        "lease",
        "completed",
        "signature",
    ],
)
async def test_native_main_context_rejects_changed_identity_or_finished_turn(native_main, change):
    runtime, _, turn, original = native_main
    context = dict(original)
    if change in {"project", "conversation", "provider"}:
        context[
            {"project": "projectId", "conversation": "conversationId", "provider": "providerId"}[
                change
            ]
        ] = "foreign"
    if change == "owner":
        context["owner"] = "bob"
    if change == "generation":
        context["generation"] += 1
    if change == "lease":
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET lease_epoch=2 WHERE id=?", (turn["id"],)),
            write=True,
        )
    if change == "completed":
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
    context["signature"] = runtime.main_capabilities.signature(
        {k: v for k, v in context.items() if k != "signature"}
    )
    if change == "signature":
        context["signature"] = "0" * 64
    with pytest.raises(DomainError, match="ACTIVE_MAIN_CONTEXT_REQUIRED"):
        await runtime.main_capabilities.call(
            "skill_read", request(context, {"name": "missing"}), "alice"
        )
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM tool_calls").fetchone()[0]
        )
        == 0
    )


async def test_native_main_http_routes_signed_context_without_accepting_worker_shape(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        path = "/v1/tool-directory/swarm_status/call"
        response = await client.post(path, json=request(context, {"swarmId": group["id"]}))
        assert response.status_code == 200 and response.json()["data"]["state"] == "succeeded"
        worker_shape = {**context, "kind": "worker"}
        response = await client.post(path, json=request(worker_shape, {"swarmId": group["id"]}))
        assert response.status_code == 409
    with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
        await runtime.main_capabilities.call(
            "reply",
            request(context, {"text": "Must not duplicate final delivery"}, "reply"),
            "alice",
        )


async def test_native_main_does_not_replay_pending_or_unknown_capabilities(native_main):
    runtime, _, _, context = native_main
    entered, release = asyncio.Event(), asyncio.Event()
    hits = []

    async def operation(args, binding):
        hits.append(binding)
        entered.set()
        await release.wait()
        raise DomainError("TOOL_OUTCOME_UNKNOWN")

    runtime.tools.add(
        Tool(
            "native_main_effect",
            "Bound effect",
            object_schema({}),
            operation,
            effect="write",
            main=True,
        )
    )
    payload = request(context)
    call = asyncio.create_task(
        runtime.main_capabilities.call("native_main_effect", payload, "alice")
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
            await runtime.main_capabilities.call("native_main_effect", payload, "alice")
        release.set()
        result = await asyncio.wait_for(call, 5)
        assert result["state"] == "unknown"
        assert (
            await runtime.main_capabilities.call("native_main_effect", payload, "alice") == result
        )
        assert len(hits) == 1 and hits[0]["taskId"] is None and hits[0]["runId"] is None
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)


async def test_stop_revokes_inflight_main_capability_and_cancels_handler(native_main):
    runtime, main, turn, context = native_main
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def operation(args, binding):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    runtime.tools.add(
        Tool(
            "native_main_wait", "Bound read", object_schema({}), operation, effect="read", main=True
        )
    )
    call = asyncio.create_task(
        runtime.main_capabilities.call("native_main_wait", request(context), "alice")
    )
    await asyncio.wait_for(entered.wait(), 5)
    await runtime.chat.interrupt("alice", main["id"], "native-stop", expected_turn_id=turn["id"])
    result = await asyncio.wait_for(call, 5)
    assert stopped.is_set() and result["state"] in {"cancelled", "unknown"}
    with pytest.raises(DomainError, match="ACTIVE_MAIN_CONTEXT_REQUIRED|TURN_INTERRUPTED"):
        await runtime.main_capabilities.call("native_main_wait", request(context), "alice")


async def test_final_main_message_retains_gateway_calls_without_executing_again(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    result = await runtime.main_capabilities.call(
        "swarm_status", request(context, {"swarmId": group["id"]}), "alice"
    )
    assert result["state"] == "succeeded"
    mid = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id FROM messages WHERE turn_id=? AND role='assistant' AND status='streaming' ORDER BY seq DESC LIMIT 1",
            (turn["id"],),
        )
    )
    await runtime.journal.finish(
        turn, mid["id"], "Actual native final answer", [], None, 1, final=True, completion=None
    )
    saved = await runtime.conversations.messages("alice", main["id"])
    assistant = next(m for m in saved["messages"] if m["id"] == mid["id"])
    step = next(m for m in saved["messages"] if m["content"].get("tool_calls"))
    calls = step["content"]["tool_calls"]
    assert len(calls) == 1 and calls[0]["function"]["name"] == "swarm_status"
    assert assistant["content"]["text"] == "Actual native final answer"
    assert step["id"] != assistant["id"] and not assistant["content"].get("tool_calls")
    results = [m for m in saved["messages"] if m["role"] == "tool"]
    assert len(results) == 1 and results[0]["content"]["tool_call_id"] == calls[0]["id"]
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM tool_calls").fetchone()[0]
        )
        == 1
    )


@pytest.mark.parametrize("final_tool", [False, True])
async def test_real_main_queue_delivers_signed_context_to_native_cli_and_keeps_tool_history(
    wake_runtime, monkeypatch, final_tool
):
    from types import SimpleNamespace

    from test_native_main import stopped
    from test_runtime import until

    runtime, main, spec, proof, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    runtime.swarms.chat = None
    group = await runtime.swarms.create(
        "alice",
        {
            "commandKey": "queued-team",
            "name": "Queued native team",
            "goal": "Read status",
            "mainConversationId": main["id"],
            "target": {"kind": "project", "projectId": "project"},
        },
    )
    await runtime.swarms.control(
        "alice", group["id"], {"commandKey": "pause-team", "expectedRevision": 1, "action": "pause"}
    )
    launches = []

    async def command(sub, *args, spec=None):
        assert sub == "launch"
        launches.append(spec)
        context_file = next(
            line.partition("=")[2]
            for line in spec["prompt"].splitlines()
            if line.startswith("ROAMI_MAIN_CONTEXT=")
        )
        context = json.loads(Path(context_file).read_text())
        assert context["signature"] not in spec["prompt"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            result = await client.post(
                "/v1/tool-directory/swarm_status/call",
                json=request(context, {"swarmId": group["id"]}),
            )
            assert result.status_code == 200 and result.json()["data"]["state"] == "succeeded"
            assert result.json()["data"]["result"]["mainConversationId"] == main["id"]
        return stopped({"session_id": proof["sessionId"], "binding": proof["sessionBinding"]})

    runtime.main_executions.executor = SimpleNamespace(command=command)
    runtime.loop.require_final_tool = final_tool
    await runtime.start()
    accepted = await runtime.chat.submit(
        "alice", main["id"], "main-cli-context", "Read original team status"
    )

    await until(
        runtime.db,
        lambda db: row(
            db, "SELECT * FROM turns WHERE id=? AND state='completed'", (accepted["turnId"],)
        ),
    )
    assert len(launches) == 1 and launches[0]["sessionId"] == proof["sessionId"]
    saved = await runtime.conversations.messages("alice", main["id"])
    calls = [call for m in saved["messages"] for call in m["content"].get("tool_calls", [])]
    native_calls = [call for call in calls if call["function"]["name"] == "swarm_status"]
    replies = [call for call in calls if call["function"]["name"] == "reply"]
    assert len(native_calls) == 1 and len(replies) == int(final_tool)
    assert any(m["content"].get("text") == "Actual native answer" for m in saved["messages"])


async def test_signed_main_discovers_main_only_operations_through_tool_list(native_main):
    runtime, _, _, context = native_main
    result = await runtime.main_capabilities.call(
        "tool_list", request(context, {"query": "swarm_plan", "limit": 20}, "discover"), "alice"
    )
    assert result["state"] == "succeeded", result
    entries = result["result"]["items"]
    assert any(entry["name"] == "swarm_plan" and entry.get("inputSchema") for entry in entries), (
        result
    )


async def test_first_reply_review_sees_actual_native_receipts_without_reexecution(native_main):
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.replies.native_main_observations import review_native_context
    from roami_agent.replies.source_review import SourceReplyReview

    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    result = await runtime.main_capabilities.call(
        "swarm_control",
        request(
            context, {"swarmId": group["id"], "expectedRevision": 1, "action": "pause"}, "pause"
        ),
        "alice",
    )
    assert result["state"] == "succeeded"

    class ReviewModel:
        model = "saved-review-route"
        settings_hash = "same-saved-parameters"

        def __init__(self):
            self.requests = []

        async def stream(self, messages, tools):
            self.requests.append(messages)
            yield ModelEvent(
                "tool",
                {
                    "id": "review",
                    "function": {
                        "name": "source_review_verdict",
                        "arguments": json.dumps({"accepted": True, "feedback": ""}),
                    },
                },
            )

    model = ReviewModel()
    reviewer = SourceReplyReview(runtime.db, lambda: model)
    prompt = [{"role": "user", "content": "Coordinate the original project team"}]
    reviewer.observe_context(turn, prompt)
    binding = {"owner": "alice", "conversation": main["id"], "turnId": turn["id"], "leaseEpoch": 1}
    verdict = await reviewer.evaluate(
        {"text": "The original Swarm is paused at revision 2."}, binding, "answer"
    )
    assert verdict.accepted and len(model.requests) == 1
    pieces = []
    for message in model.requests[0]:
        content = message.get("content")
        pieces.extend(
            [content]
            if isinstance(content, str)
            else [part.get("text", "") for part in content or []]
        )
    objects = []
    for piece in pieces:
        try:
            objects.append(json.loads(piece))
        except ValueError:
            pass
    receipts = [
        json.loads(message["content"])
        for value in objects
        if isinstance(value, dict)
        for message in value.get("currentMainContext", [])
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    assert result["result"] in receipts
    _, source = await reviewer.sources(binding)
    observed = source["nativeMainObservations"]
    assert observed and review_native_context([*prompt, *observed], observed) == [
        *prompt,
        *observed,
    ]
    calls = await runtime.db.call(
        lambda db: db.execute(
            "SELECT tool_name FROM tool_calls WHERE turn_id=?", (turn["id"],)
        ).fetchall()
    )
    assert [call["tool_name"] for call in calls] == ["swarm_control"]


@pytest.mark.parametrize("change", ["deleted result", "unattested call"])
async def test_reply_review_rejects_changed_or_unattested_native_evidence(native_main, change):
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.replies.source_review import SourceReplyReview

    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    await runtime.main_capabilities.call(
        "swarm_status", request(context, {"swarmId": group["id"]}, "status"), "alice"
    )

    class ReviewModel:
        model = "saved-review-route"
        settings_hash = "same-saved-parameters"

        async def stream(self, messages, tools):
            await runtime.db.call(
                lambda db: db.execute(
                    "UPDATE messages SET deleted_ms=1 WHERE id IN (SELECT result_message_id FROM tool_calls WHERE turn_id=?)",
                    (turn["id"],),
                ),
                write=True,
            )
            yield ModelEvent(
                "tool",
                {
                    "id": "review",
                    "function": {
                        "name": "source_review_verdict",
                        "arguments": json.dumps({"accepted": True, "feedback": ""}),
                    },
                },
            )

    model = ReviewModel()
    reviewer = SourceReplyReview(runtime.db, lambda: model)
    reviewer.observe_context(
        turn, [{"role": "user", "content": "Coordinate the original project team"}]
    )
    binding = {"owner": "alice", "conversation": main["id"], "turnId": turn["id"], "leaseEpoch": 1}
    if change == "unattested call":
        await runtime.db.call(
            lambda db: db.execute(
                "DELETE FROM events WHERE turn_id=? AND kind='capability.started'", (turn["id"],)
            ),
            write=True,
        )
        _, source = await reviewer.sources(binding)
        assert source["nativeMainObservations"] == []
    else:
        with pytest.raises(DomainError, match="REPLY_REVIEW_SOURCE_CHANGED"):
            await reviewer.evaluate({"text": "The Swarm has been inspected."}, binding, "answer")


async def test_native_failure_returns_registered_call_id_for_real_blocker_evidence(native_main):
    from roami_agent.storage.swarm_goal_checkpoint import failed_step

    runtime, main, turn, context = native_main

    async def unavailable(args, binding):
        raise DomainError("RESOURCE_UNAVAILABLE", 503)

    runtime.tools.add(
        Tool(
            "native_unavailable",
            "Actual dependency failure",
            object_schema({}),
            unavailable,
            main=True,
        )
    )
    payload = request(context, key="dependency-refusal")
    result = await runtime.main_capabilities.call("native_unavailable", payload, "alice")
    assert result["state"] == "failed" and result["toolCallId"].startswith("native-main-")
    binding = {"owner": "alice", "conversation": main["id"], "turnId": turn["id"]}
    proof = await runtime.db.call(lambda db: failed_step(db, binding, result["toolCallId"]))
    assert proof["error"] == "RESOURCE_UNAVAILABLE" and proof["tool"] == "native_unavailable"
    with pytest.raises(DomainError, match="SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED"):
        await runtime.db.call(lambda db: failed_step(db, binding, result["requestId"]))
    assert await runtime.main_capabilities.call("native_unavailable", payload, "alice") == result


async def test_native_main_updates_its_existing_roster_through_signed_capabilities(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    scope = {"swarmId": group["id"]}
    registration = request(
        context,
        {
            **scope,
            "expectedRevision": 1,
            "members": [{"name": "review", "executor": "claude", "duty": "Review references"}],
        },
        key="new-review-role",
    )
    added = await runtime.main_capabilities.call("swarm_members_register", registration, "alice")
    assert added["state"] == "succeeded"
    ident = added["result"]["members"][0]["id"]
    retirement = request(
        context,
        {**scope, "expectedRevision": 2, "action": "retire", "memberIds": [ident]},
        key="remove-review-role",
    )
    retired = await runtime.main_capabilities.call("swarm_members_lifecycle", retirement, "alice")
    assert retired["state"] == "succeeded" and retired["result"]["members"][0]["id"] == ident
    assert (
        await runtime.main_capabilities.call("swarm_members_lifecycle", retirement, "alice")
        == retired
    )
    status = await runtime.main_capabilities.call(
        "swarm_status", request(context, scope, key="roster"), "alice"
    )
    snapshot = status["result"]
    assert snapshot["mainConversationId"] == main["id"] and not snapshot["members"]
    assert snapshot["retiredMembers"][0]["id"] == ident
