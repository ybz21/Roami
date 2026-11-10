"""Rejected calls retain attempted input without claiming execution or echoing values."""

import json

import pytest
from test_argument_repair_progress import claimed_turn, register_probe
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import message


@pytest.mark.parametrize(
    "name,raw,error",
    [
        ("probe", '{"a":"private-invalid-value","b":2}', "INVALID_TOOL_ARGUMENTS"),
        ("unregistered", '{"command":"roami task_steer --taskId original"}', "TOOL_UNAVAILABLE"),
        ("probe", '{"a":', "INVALID_TOOL_ARGUMENTS"),
        ("probe", "[1,2]", "INVALID_TOOL_ARGUMENTS"),
    ],
)
async def test_validation_rejection_keeps_source_and_never_starts_handler(store, name, raw, error):
    runtime, effects = Runtime(store, ConversationModel()), []
    register_probe(runtime, effects)
    try:
        turn = await claimed_turn(runtime)
        call = {"id": "attempt", "function": {"name": name, "arguments": raw}}
        mid = await store.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        result = await runtime.gateway.invoke(
            turn, mid, call, "main", {"owner": "alice", "turnId": turn["id"]}
        )
        assert result["error"] == error
        assert result["executionStarted"] is False and result["failurePhase"] == "validation"
        assert not effects and "private-invalid-value" not in json.dumps(result)
        receipt = await store.call(
            lambda db: row(
                db,
                "SELECT x.*,m.content_json FROM tool_calls x JOIN messages m "
                "ON m.id=x.assistant_message_id WHERE x.turn_id=?",
                (turn["id"],),
            )
        )
        assert receipt["state"] == "failed" and receipt["tool_name"] == name
        assert json.loads(receipt["content_json"])["tool_calls"][0] == call
        if raw.startswith('{"') and not raw.endswith(":"):
            assert json.loads(receipt["arguments_json"]) == json.loads(raw)
        assert not await store.call(
            lambda db: row(
                db, "SELECT id FROM events WHERE turn_id=? AND kind='tool.started'", (turn["id"],)
            )
        )
        assert await store.call(
            lambda db: row(
                db, "SELECT id FROM events WHERE turn_id=? AND kind='tool.completed'", (turn["id"],)
            )
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("repeat", [False, True])
async def test_legacy_command_rejection_has_guided_repair_and_only_stalls_without_progress(
    store, monkeypatch, repeat
):
    wrong = "roami task_status --input '{}'"

    class Main:
        model, calls = "command-admission-fixture", 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 2:
                error = json.loads(messages[-1]["content"])
                assert error["error"] == "USE_REGISTERED_CLI_CAPABILITY"
                assert error["executionStarted"] is False
                assert error["failurePhase"] == "command_admission"
                assert "tool_list" in error["recovery"]
            if self.calls <= 2:
                yield ModelEvent(
                    "tool",
                    {
                        "id": str(self.calls),
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {"command": wrong if repeat or self.calls == 1 else "roami help"}
                            ),
                        },
                    },
                )
            else:
                yield ModelEvent("text", "Commands inspected.")

    async def never_execute(*args, **kwargs):
        pytest.fail("Command admission/help must not launch a subprocess")

    monkeypatch.setattr("roami_agent.tools.foundations.execute", never_execute)
    model = Main()
    runtime = Runtime(store, model)

    async def legacy_rejection(args, binding):
        raise DomainError("USE_REGISTERED_CLI_CAPABILITY")

    monkeypatch.setattr(runtime.tools.registry["shell"], "handler", legacy_rejection)
    try:
        turn = await claimed_turn(runtime)
        if repeat:
            with pytest.raises(DomainError, match="TOOL_ARGUMENT_REPAIR_STALLED"):
                await runtime.loop.run(turn, "main")
            assert model.calls == 2
        else:
            assert await runtime.loop.run(turn, "main") == "Commands inspected."
            assert model.calls == 3
        receipts = await store.call(
            lambda db: rows(
                db, "SELECT * FROM tool_calls WHERE turn_id=? ORDER BY created_ms", (turn["id"],)
            )
        )
        assert len(receipts) == 2
        assert json.loads(receipts[0]["arguments_json"]) == {"command": wrong}
        assert [r["state"] for r in receipts] == ["failed", "failed" if repeat else "succeeded"]
    finally:
        await runtime.close()
