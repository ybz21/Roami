"""A rejected text draft must recover through an actual provider tool call."""

import json

import httpx
from test_argument_repair_progress import claimed_turn

from roami_agent.app import Runtime
from roami_agent.providers.chat_completions import ChatCompletions

CHOICE = {"type": "function", "function": {"name": "reply"}}


def response(delta):
    event = {
        "choices": [{"index": 0, "delta": delta, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=b"data: " + json.dumps(event).encode() + b"\n\ndata: [DONE]\n\n",
    )


async def test_repeated_plain_final_recovers_via_provider_tool_selection(store):
    value = {"label": "exact user wording", "enabled": False, "count": 2, "extra": None}
    requests = []

    def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tool_choice") != CHOICE:
            return response({"content": "<reply>" + json.dumps(value) + "</reply>"})
        return response(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_recovered_reply",
                        "type": "function",
                        "function": {"name": "reply", "arguments": json.dumps({"json": value})},
                    }
                ]
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client)
        runtime = Runtime(store, model, require_final_tool=True)
        try:
            turn = await claimed_turn(runtime)
            answer = await runtime.loop.run(turn, "main")
            assert json.loads(answer) == value
            assert len(requests) == 2
            assert "tool_choice" not in requests[0]
            assert requests[1]["tool_choice"] == CHOICE
            events = await runtime.conversations.events("alice", turn["conversation_id"])
            assert [e["payload"]["text"] for e in events if e["kind"] == "message.delta"] == [
                answer
            ]
        finally:
            await runtime.close()


async def test_content_rejection_releases_required_selection_for_a_question(store):
    from roami_agent.replies.source_review import EXTRACTION_INSTRUCTIONS, REVIEW_INSTRUCTIONS

    main_requests, review_requests = [], []

    def tool_delta(name, arguments):
        return {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_" + name + "_" + str(len(main_requests) + len(review_requests)),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        }

    def serve(request):
        body = json.loads(request.content)
        first = body["messages"][0]["content"]
        if first == REVIEW_INSTRUCTIONS:
            review_requests.append(body)
            payload = json.loads(body["messages"][-1]["content"])
            question = payload["draftKind"] == "question"
            return response(
                tool_delta(
                    "source_review_verdict",
                    {"accepted": question, "feedback": "" if question else "Ask for permission"},
                )
            )
        if not body.get("tools"):
            review_requests.append(body)
            return response({"content": "[]" if first == EXTRACTION_INSTRUCTIONS else "{}"})
        main_requests.append(body)
        if len(main_requests) == 1:
            return response({"content": "Draft without a tool"})
        if len(main_requests) == 2:
            return response(tool_delta("reply", {"text": "Proposed answer"}))
        return response(
            tool_delta("ask_user", {"prompt": "May I proceed?", "options": ["Proceed", "Wait"]})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client)
        runtime = Runtime(store, model, require_final_tool=True, review_replies=True)
        try:
            turn = await claimed_turn(runtime)
            assert await runtime.loop.run(turn, "main") == ""
            events = await runtime.conversations.events("alice", turn["conversation_id"])
            completed = [event for event in events if event["kind"] == "message.completed"]
            assert completed[-1]["payload"]["question"]["prompt"] == "May I proceed?"
            assert [body.get("tool_choice") for body in main_requests] == [None, CHOICE, None]
            assert review_requests and all("tool_choice" not in body for body in review_requests)
        finally:
            await runtime.close()


async def test_ordinary_main_and_worker_requests_do_not_inherit_selection(store):
    from roami_agent.protocol.model_tool_selection import required_final_reply, select_final_reply

    requests = []

    def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        return response({"content": "Worker result"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client)
        runtime = Runtime(store, model, require_final_tool=True)
        try:
            async with select_final_reply(True):
                assert (
                    await runtime.loop.run(await claimed_turn(runtime), "worker") == "Worker result"
                )
                assert required_final_reply.get() is True
            assert required_final_reply.get() is False
            assert len(requests) == 1 and "tool_choice" not in requests[0]
        finally:
            await runtime.close()


async def test_required_selection_survives_real_private_bridge_without_route_changes(tmp_path):
    from roami_agent.improvement.integrations.model_gateway import ModelGateway
    from roami_agent.protocol.model_tool_selection import select_final_reply
    from roami_agent.providers.model_bridge_transport import PrivateModelBridgeTransport

    requests = []

    def serve(request):
        requests.append(json.loads(request.content))
        return response({"content": "Model output"})

    tools = [{"type": "function", "function": {"name": "reply"}}]
    socket = tmp_path / "relay.sock"
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as host_client:
        host = ChatCompletions(
            "http://localhost/v1",
            "saved-model",
            client=host_client,
            parameters={"temperature": 0.25},
        )
        async with (
            ModelGateway(socket, {"main": host, "worker": host}) as gateway,
            httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(socket))) as client,
        ):
            actor = ChatCompletions("http://localhost/v1/main", "main", client=client)
            async with select_final_reply(True):
                assert [event async for event in actor.stream([], tools)]
            worker = ChatCompletions("http://localhost/v1/worker", "worker", client=client)
            assert [event async for event in worker.stream([], [])]
            assert gateway.errors == []
    assert [body.get("tool_choice") for body in requests] == [CHOICE, None]
    assert all(body["model"] == "saved-model" and body["temperature"] == 0.25 for body in requests)


async def test_bridge_rejects_unavailable_or_non_main_forced_tools_before_model_call(tmp_path):
    from roami_agent.improvement.integrations.model_gateway import ModelGateway

    class NeverCalled:
        async def stream(self, messages, tools):
            raise AssertionError("invalid selection reached a model")
            yield

    socket = tmp_path / "relay.sock"
    tools = [{"type": "function", "function": {"name": "reply"}}]
    inputs = [
        ("main", "required", tools),
        ("main", True, tools),
        ("main", {"type": "function", "function": {"name": "bash"}}, tools),
        ("main", {**CHOICE, "extra": True}, tools),
        ("main", CHOICE, []),
        ("main", CHOICE, [None]),
        ("main", CHOICE, [{"function": {"name": "reply"}}]),
        ("worker", CHOICE, tools),
        ("memory", CHOICE, tools),
    ]
    async with (
        ModelGateway(socket, {"main": NeverCalled()}) as gateway,
        httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))) as client,
    ):
        for role, choice, catalog in inputs:
            result = await client.post(
                "http://localhost/v1/" + role + "/chat/completions",
                json={"messages": [], "tools": catalog, "tool_choice": choice},
            )
            assert result.status_code == 400
            assert result.json()["error"]["code"] == "RSI_GATEWAY_INPUT"
        assert gateway.errors == ["RSI_GATEWAY_INPUT"] * len(inputs)


async def test_selected_tool_has_a_distinct_cache_key_and_preserves_sampling():
    from roami_agent.protocol.model_tool_selection import select_final_reply

    requests = []

    def serve(request):
        requests.append(json.loads(request.content))
        return response({"content": "Draft"})

    tools = [{"type": "function", "function": {"name": "reply"}}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions(
            "http://localhost/v1",
            "saved-model",
            client=client,
            parameters={"temperature": 0.25},
            capabilities={"prompt_cache_key": True},
            cache={"namespace": "tool-selection-control"},
        )
        before = model.settings_hash
        assert [event async for event in model.stream([], tools)]
        async with select_final_reply(True):
            assert [event async for event in model.stream([], tools)]
        assert [event async for event in model.stream([], tools)]
        assert model.settings_hash == before
        assert model.parameters == {"temperature": 0.25}
    assert requests[0]["prompt_cache_key"] == requests[2]["prompt_cache_key"]
    assert requests[1]["prompt_cache_key"] != requests[0]["prompt_cache_key"]
    assert [body.get("tool_choice") for body in requests] == [None, CHOICE, None]


async def test_unavailable_required_reply_is_rejected_without_http():
    import pytest

    from roami_agent.protocol.errors import DomainError
    from roami_agent.protocol.model_tool_selection import select_final_reply

    def never_called(request):
        raise AssertionError("unavailable required tool reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(never_called)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client)
        for tools in [
            [],
            [None],
            [{"function": None}],
            [{"type": "custom", "function": {"name": "reply"}}],
        ]:
            async with select_final_reply(True):
                with pytest.raises(DomainError, match="MODEL_REPLY_TOOL_REQUIRED"):
                    _ = [event async for event in model.stream([], tools)]


async def test_old_actor_cannot_claim_final_submission_recovery(monkeypatch):
    import pytest

    from roami_agent.improvement.evaluation.execution import containers
    from roami_agent.protocol.errors import DomainError
    from roami_agent.server.configuration import Settings

    label = "1"

    async def inspect(*args):
        assert args[:2] == ("image", "inspect")
        return json.dumps(
            [
                {
                    "Id": "candidate",
                    "Config": {
                        "Labels": {
                            "org.roami.rsi.shared-daily-policy": "6",
                            "org.roami.rsi.role-instructions": "1",
                            "org.roami.rsi.source-reply-review": "6",
                            "org.roami.rsi.final-reply-tool": label,
                        }
                    },
                }
            ]
        ).encode()

    monkeypatch.setattr(containers, "docker_command", inspect)
    executor = containers.ContainerExecutor(Settings())
    with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED") as error:
        await executor.preflight()
    assert error.value.execution_diagnostics["requirements"] == [
        {"label": "org.roami.rsi.final-reply-tool", "required": "2", "observed": "1"}
    ]
    assert (await executor.preflight(model_inputs=False))["image_id"] == "candidate"
    label = "2"
    assert (await executor.preflight())["image_id"] == "candidate"


async def test_provider_ignoring_selection_cannot_execute_a_different_tool(store):
    from roami_agent.protocol.tools import Tool, object_schema

    requests, writes = [], []

    def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return response({"content": "Unsubmitted answer"})
        name, args = (
            ("write_probe", {}) if len(requests) == 2 else ("reply", {"text": "Safe answer"})
        )
        return response(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_" + str(len(requests)),
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ]
            }
        )

    async def write(args, binding):
        writes.append(args)
        return {"written": True}

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client)
        runtime = Runtime(store, model, require_final_tool=True)
        runtime.tools.add(
            Tool(
                "write_probe", "Fixture write", object_schema({}), write, effect="write", main=True
            )
        )
        try:
            assert await runtime.loop.run(await claimed_turn(runtime), "main") == "Safe answer"
            assert writes == []
            assert [body.get("tool_choice") for body in requests] == [None, CHOICE, CHOICE]
        finally:
            await runtime.close()


async def test_provider_rejecting_selection_preserves_failure_without_auto_fallback(store):
    import pytest

    from roami_agent.protocol.errors import DomainError

    requests = []

    def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        return (
            response({"content": "Unsubmitted answer"})
            if len(requests) == 1
            else httpx.Response(400, json={"error": "unsupported selection"})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        model = ChatCompletions("http://localhost/v1", "fixture", client=client, max_retries=0)
        runtime = Runtime(store, model, require_final_tool=True)
        try:
            turn = await claimed_turn(runtime)
            with pytest.raises(DomainError, match="MODEL_HTTP_400"):
                await runtime.loop.run(turn, "main")
            assert len(requests) == 2 and requests[1]["tool_choice"] == CHOICE
            events = await runtime.conversations.events("alice", turn["conversation_id"])
            assert not any(
                event["kind"] in {"message.delta", "message.completed"} for event in events
            )
        finally:
            await runtime.close()
