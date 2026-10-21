"""Schema repair must make progress without imposing a normal tool budget."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tool_arguments import ToolArgumentsError, validate_tool_arguments
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def test_nullable_hash_diagnostic_explains_schema_alternatives_without_input_values():
    alternatives = [{"type": "string", "pattern": "^[a-f0-9]{64}$"}, {"type": "null"}]
    schema = object_schema({"expectedSha256": {"anyOf": alternatives}})
    with pytest.raises(ToolArgumentsError) as error:
        validate_tool_arguments(schema, {"expectedSha256": "private-invalid-hash"})
    assert error.value.issues == [
        {"path": ["expectedSha256"], "rule": "anyOf", "expectedAlternatives": alternatives}
    ]
    assert "private-invalid-hash" not in json.dumps(error.value.issues)


class ArgumentModel:
    model = "argument-progress-fixture"

    def __init__(self, batches):
        self.batches, self.calls = batches, 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls > len(self.batches):
            yield ModelEvent("text", "Done")
            return
        for number, arguments in enumerate(self.batches[self.calls - 1]):
            yield ModelEvent(
                "tool",
                {
                    "id": f"{self.calls}-{number}",
                    "function": {"name": "probe", "arguments": json.dumps(arguments)},
                },
            )


async def claimed_turn(runtime):
    conversation = await runtime.conversations.create("alice")
    receipt = await runtime.conversations.accept(
        "alice", conversation["id"], "request", "Perform the requested operations"
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (receipt["turnId"],)
        )
    )
    return await runtime.mailbox.claim(job)


def register_probe(runtime, effects):
    async def execute(arguments, binding):
        effects.append(arguments)
        return {"observed": True}

    runtime.tools.directory = None
    runtime.tools.add(
        Tool(
            "probe",
            "Run the operation",
            object_schema({"a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"]),
            execute,
            main=True,
            effect="write",
        )
    )


async def test_repeated_schema_failure_stops_after_guided_repair_without_side_effects(store):
    model, effects = ArgumentModel([[{}]] * 30), []
    runtime = Runtime(store, model)
    register_probe(runtime, effects)
    try:
        turn = await claimed_turn(runtime)
        with pytest.raises(DomainError) as error:
            await runtime.loop.run(turn, "main")
        assert error.value.code == "TOOL_ARGUMENT_REPAIR_STALLED"
        assert model.calls == 2 and not effects
        failure = await store.call(
            lambda db: row(
                db,
                "SELECT payload_json FROM events WHERE turn_id=? AND kind='turn.failed'",
                (turn["id"],),
            )
        )
        assert json.loads(failure["payload_json"])["error"] == "TOOL_ARGUMENT_REPAIR_STALLED"
    finally:
        await runtime.close()


async def test_changing_schema_issues_and_parallel_calls_can_be_repaired(store):
    model = ArgumentModel([[{}, {}], [{"a": 1}], [{"a": 1, "b": 2}]])
    runtime, effects = Runtime(store, model), []
    register_probe(runtime, effects)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "main") == "Done"
        assert model.calls == 4 and effects == [{"a": 1, "b": 2}]
    finally:
        await runtime.close()


async def test_changed_arguments_with_the_same_schema_issue_can_continue_repair(store):
    model = ArgumentModel([[{"a": "first", "b": 2}], [{"a": "second", "b": 2}], [{"a": 1, "b": 2}]])
    runtime, effects = Runtime(store, model), []
    register_probe(runtime, effects)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "main") == "Done"
        assert model.calls == 4 and effects == [{"a": 1, "b": 2}]
    finally:
        await runtime.close()


async def test_valid_tool_rounds_continue_beyond_old_step_limit(store):
    model = ArgumentModel([[{"a": number, "b": 1}] for number in range(25)])
    runtime, effects = Runtime(store, model), []
    register_probe(runtime, effects)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "main") == "Done"
        assert model.calls == 26 and len(effects) == 25
    finally:
        await runtime.close()


@pytest.mark.parametrize("invalid_hash", ["NULL", "", "not-a-digest"])
async def test_file_hash_repair_guidance_creates_and_reads_real_file(store, tmp_path, invalid_hash):
    path = tmp_path / "answer.txt"

    class FileModel:
        model = "file-null-repair"

        async def stream(self, messages, tools):
            results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if len(results) == 0:
                expected = invalid_hash
            elif len(results) == 1:
                assert not path.exists()
                assert results[-1]["executionStarted"] is False
                assert "actual JSON null" in results[-1]["recovery"]
                expected = None
            elif len(results) == 2:
                assert path.read_text() == "Verified answer"
                yield ModelEvent(
                    "tool",
                    {
                        "id": "read-back",
                        "function": {"name": "read", "arguments": json.dumps({"path": str(path)})},
                    },
                )
                return
            else:
                assert results[-1]["data"] == "Verified answer"
                yield ModelEvent("text", "Read back verified")
                return
            yield ModelEvent(
                "tool",
                {
                    "id": "write-" + str(len(results)),
                    "function": {
                        "name": "write",
                        "arguments": json.dumps(
                            {
                                "path": str(path),
                                "expectedSha256": expected,
                                "content": "Verified answer",
                            }
                        ),
                    },
                },
            )

    model = FileModel()
    runtime = Runtime(store, model, worker_model=model, settings=Settings(shell_roots=(tmp_path,)))
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "worker") == "Read back verified"
        with pytest.raises(DomainError, match="FILE_CHANGED"):
            await runtime.files.write(
                {"path": str(path), "expectedSha256": None, "content": "overwrite"}, {}
            )
        assert path.read_text() == "Verified answer"
    finally:
        await runtime.close()
