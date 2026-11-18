import asyncio
import copy

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.native_main import NativeMain


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
