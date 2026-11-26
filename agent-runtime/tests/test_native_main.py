import asyncio
import copy

import pytest

from roami_agent.protocol.errors import DomainError
from roami_okr.native_main import NativeMain


def fixture_binding():
    return {
        "owner_id": "alice",
        "project_id": "project-a",
        "conversation_id": "original-main",
        "executor": "claude",
        "model": "free",
        "provider_id": "native-provider",
        "session_id": "native-session",
        "launch_key": "prepared-main",
        "binding": {
            "id": "native-session",
            "providerConversationId": "native-provider",
            "pid": 1,
            "directory": "/project-a",
        },
    }


def fixture_turn():
    return {"id": "turn-one", "conversation_id": "original-main", "owner_id": "alice"}


def stopped(binding, *, state="succeeded", known=True):
    return {
        "session": binding["session_id"],
        "sessionBinding": binding["binding"],
        "result": {
            "state": state,
            "inputStopped": True,
            "outcomeKnown": known,
            "summary": "Actual native answer",
        },
    }


async def test_native_main_reuses_same_provider_and_never_reexecutes_native_tools():
    binding = fixture_binding()
    calls = []

    async def command(sub, *args, **kwargs):
        calls.append((sub, args, kwargs))
        return stopped(binding)

    model = NativeMain(binding, fixture_turn(), command)
    assert model.with_model("free", free_only=True) is model
    parts = [
        event
        async for event in model.stream(
            [{"role": "user", "content": "Coordinate the original team"}],
            [{"function": {"name": "delegate"}}],
        )
    ]
    assert [(p.kind, p.value) for p in parts] == [("text", "Actual native answer")]
    spec = calls[0][2]["spec"]
    assert spec["sessionId"] == "native-session" and spec["preparedFrom"] == "prepared-main"
    assert spec["executor"] == "claude" and "model" not in spec
    assert "original-main" in spec["prompt"] and "project-a" in spec["prompt"]
    assert len(calls) == 1
    await anext(model.stream([{"role": "user", "content": "Coordinate the original team"}], []))
    assert calls[1][2]["spec"]["key"] == spec["key"]


async def test_native_main_defers_proven_unsubmitted_busy_input_with_identical_identity():
    binding = fixture_binding()
    calls, delays = [], []

    async def command(sub, *args, **kwargs):
        calls.append((sub, args, copy.deepcopy(kwargs)))
        if len(calls) < 3:
            raise DomainError("SESSION_NOT_IDLE", 409)
        return stopped(binding)

    async def wait(delay):
        delays.append(delay)

    model = NativeMain(binding, fixture_turn(), command, sleep=wait)
    assert (await anext(model.stream([{"role": "user", "content": "continue"}], []))).value
    assert len(calls) == 3 and all(call == calls[0] for call in calls)
    assert delays == [1, 2]


async def test_cancelling_unsubmitted_main_wait_does_not_cancel_previous_provider_input():
    calls, waiting = [], asyncio.Event()

    async def command(sub, *args, **kwargs):
        calls.append(sub)
        raise DomainError("SESSION_NOT_IDLE", 409)

    async def wait(_):
        waiting.set()
        await asyncio.Event().wait()

    model = NativeMain(fixture_binding(), fixture_turn(), command, sleep=wait)
    task = asyncio.create_task(anext(model.stream([], [])))
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["launch"]


@pytest.mark.parametrize(
    "code",
    [
        "SESSION_PROVIDER_BINDING_CHANGED",
        "CODING_EXECUTOR_UNAVAILABLE",
        "EXECUTION_LAUNCH_UNCERTAIN",
    ],
)
async def test_native_main_never_replays_uncertain_launch_or_changed_binding(code):
    calls = []

    async def command(sub, *args, **kwargs):
        calls.append(sub)
        raise DomainError(code, 409)

    with pytest.raises(DomainError, match=code):
        await anext(NativeMain(fixture_binding(), fixture_turn(), command).stream([], []))
    assert calls == ["launch"]


@pytest.mark.parametrize(
    "change",
    [
        "provider",
        "session",
        "directory",
        "unknown",
        "failed",
        "empty",
        "owner",
        "conversation",
        "paid",
    ],
)
async def test_native_main_rejects_changed_scope_or_unverified_outcome(change):
    binding, turn = fixture_binding(), fixture_turn()
    response = copy.deepcopy(stopped(binding))
    if change == "provider":
        response["sessionBinding"]["providerConversationId"] = "other"
    elif change == "session":
        response["session"] = "other"
    elif change == "directory":
        response["sessionBinding"]["directory"] = "/other"
    elif change == "unknown":
        response["result"]["outcomeKnown"] = False
    elif change == "failed":
        response["result"]["state"] = "failed"
    elif change == "empty":
        response["result"]["summary"] = ""
    elif change == "owner":
        turn["owner_id"] = "bob"
    elif change == "conversation":
        turn["conversation_id"] = "homepage"

    async def command(*args, **kwargs):
        return response

    model = NativeMain(binding, turn, command)
    with pytest.raises(DomainError):
        if change == "paid":
            model.with_model("paid")
        else:
            await anext(model.stream([], []))


@pytest.mark.parametrize("known", [True, False])
async def test_native_main_cancellation_calls_real_go_cancel(known):
    binding = fixture_binding()
    launched, calls = asyncio.Event(), []

    async def command(sub, *args, **kwargs):
        calls.append(sub)
        if sub == "launch":
            launched.set()
            return {
                "session": binding["session_id"],
                "sessionBinding": binding["binding"],
                "state": "running",
            }
        if sub == "cancel":
            return stopped(binding, state="cancelled", known=known)

    async def wait(_):
        await asyncio.Event().wait()

    model = NativeMain(binding, fixture_turn(), command, sleep=wait)
    task = asyncio.create_task(anext(model.stream([], [])))
    await launched.wait()
    task.cancel("NEW_USER_INTENT")
    with pytest.raises(asyncio.CancelledError if known else DomainError):
        await task
    assert calls == ["launch", "cancel"]


@pytest.mark.parametrize("poll_error", [False, True])
async def test_native_main_waits_for_initial_unknown_and_reuses_the_same_launch(poll_error):
    binding = fixture_binding()
    pending = {
        "session": binding["session_id"],
        "sessionBinding": binding["binding"],
        "state": "unknown",
        "observationErrorCode": "SESSION_LIFECYCLE_UNKNOWN",
    }
    receipts = [pending, {**pending, "state": "running"}, stopped(binding)]
    calls = []
    errors = poll_error

    async def command(sub, *args, **kwargs):
        nonlocal errors
        calls.append((sub, args, kwargs))
        if sub == "launch":
            return copy.deepcopy(pending)
        if sub == "reconcile-session":
            raise DomainError("CODING_EXECUTOR_UNAVAILABLE", 503)
        if sub == "status":
            if errors:
                errors = False
                raise DomainError("CODING_EXECUTOR_UNAVAILABLE", 503)
            return copy.deepcopy(receipts.pop(0))
        raise AssertionError(sub)

    async def sleep(_):
        pass

    model = NativeMain(binding, fixture_turn(), command, sleep=sleep)
    parts = [part async for part in model.stream([{"role": "user", "content": "Continue"}], [])]
    assert [(part.kind, part.value) for part in parts] == [("text", "Actual native answer")]
    launches = [call for call in calls if call[0] == "launch"]
    assert len(launches) == 1
    key = launches[0][2]["spec"]["key"]
    assert all(call[1] == ("--key", key) for call in calls if call[0] != "launch")


async def test_native_main_reconciles_unknown_only_from_the_same_execution_proof():
    binding = fixture_binding()
    pending = {
        "session": binding["session_id"],
        "sessionBinding": binding["binding"],
        "state": "unknown",
    }
    calls = []

    async def command(sub, *args, **kwargs):
        calls.append((sub, args, kwargs))
        return stopped(binding) if sub == "reconcile-session" else pending

    async def sleep(_):
        pass

    parts = [
        part
        async for part in NativeMain(binding, fixture_turn(), command, sleep=sleep).stream([], [])
    ]
    assert [(part.kind, part.value) for part in parts] == [("text", "Actual native answer")]
    assert [call[0] for call in calls].count("launch") == 1
    assert [call[0] for call in calls].count("reconcile-session") == 1
    key = calls[0][2]["spec"]["key"]
    assert all(call[1] == ("--key", key) for call in calls[1:])


async def test_native_main_rejects_provider_change_while_waiting_for_startup():
    binding = fixture_binding()
    pending = {
        "session": binding["session_id"],
        "sessionBinding": binding["binding"],
        "state": "unknown",
    }

    async def command(sub, *args, **kwargs):
        if sub == "launch":
            return pending
        return {**pending, "session": "another-session"}

    async def sleep(_):
        pass

    with pytest.raises(DomainError, match="SESSION_PROVIDER_BINDING_CHANGED"):
        await anext(NativeMain(binding, fixture_turn(), command, sleep=sleep).stream([], []))


async def test_native_main_exposes_current_host_read_schema_without_native_tool_execution():
    import json

    binding, calls = fixture_binding(), []

    class Capabilities:
        async def brief(self, binding, turn):
            return "Use this turn's signed capability context."

    async def command(sub, *args, **kwargs):
        calls.append(kwargs["spec"])
        return stopped(binding)

    read = {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}},
                "required": ["path"],
            },
        },
    }
    model = NativeMain(binding, fixture_turn(), command, capabilities=Capabilities())
    messages = [{"role": "user", "content": "Continue this project"}]
    await anext(model.stream(messages, [read, {"function": {"name": "reply"}}]))
    prompt = calls[0]["prompt"]
    encoded_schemas = prompt.split("contexts from old transcripts.\n", 1)[1].split(
        "\nEnd host capability schemas.", 1
    )[0]
    assert json.loads(encoded_schemas) == [read]
    assert "artifact://" in prompt and "not native tools" in prompt
    await anext(model.stream(messages, []))
    assert calls[1]["key"] == calls[0]["key"]
