"""The evaluation lane waits for native work without fabricating task acceptance."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation_tasks import bind_evaluation_tasks, settle_evaluation_tasks
from roami_agent.improvement.executors import NativeFilesExecutor
from roami_agent.improvement.protocol_suite import protocol_suite
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def test_main_handoff_waits_for_worker_artifact_and_completion(store, tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()

    class Main:
        model = "fixture-main"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "handoff",
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps(
                                {
                                    "goal": "Save output.json with {ok:true} in " + str(workspace),
                                    "requestComplete": True,
                                    "target": {"kind": "new_session", "directory": str(workspace)},
                                    "routing": {
                                        "explicitExecutor": None,
                                        "complexity": "bounded",
                                        "complexityBasis": {"scope": "One bounded JSON file"},
                                        "routingExplanation": "Use the prepared local workspace",
                                    },
                                }
                            ),
                        },
                    },
                )
            else:
                yield ModelEvent("text", "The file is ready for independent acceptance.")

    class Worker:
        model = "fixture-worker"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "save",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {
                                    "path": "output.json",
                                    "expectedSha256": None,
                                    "content": '{"ok":true}',
                                }
                            ),
                        },
                    },
                )
            else:
                yield ModelEvent("text", "Saved output.json.")

    main, worker = Main(), Worker()
    runtime = Runtime(
        store,
        main,
        worker_model=worker,
        memory_model=Main(),
        settings=Settings(shell_roots=(workspace,)),
    )
    bind_evaluation_tasks(runtime, workspace)
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("owner")
        receipt = await runtime.chat.submit(
            "owner",
            conversation["id"],
            "one",
            "Save output.json with {ok:true} in " + str(workspace),
        )
        async with asyncio.timeout(5):
            while (
                await store.call(
                    lambda db: row(db, "SELECT state FROM turns WHERE id=?", (receipt["turnId"],))
                )
            )["state"] != "completed":
                await asyncio.sleep(0.01)
            await settle_evaluation_tasks(store)
        assert json.loads((workspace / "output.json").read_text()) == {"ok": True}
        assert worker.calls == 2 and main.calls >= 2
        task = await store.call(lambda db: row(db, "SELECT * FROM tasks"))
        assert task["state"] == "waiting_user"
    finally:
        await runtime.close()


async def test_task_lane_rejects_foreign_workspace_and_unknown_writes(tmp_path):
    native = SimpleNamespace()
    runtime = SimpleNamespace(dispatch=SimpleNamespace(native_executor=native))
    bind_evaluation_tasks(runtime, tmp_path)
    task = {
        "intent_json": json.dumps(
            {"target": {"kind": "new_session", "directory": str(tmp_path / "other")}}
        )
    }
    with pytest.raises(DomainError, match="TASK_WORKSPACE_REQUIRED"):
        async with native.workspace_factory(None, task, {"id": "one"}):
            raise AssertionError("Foreign workspace must not be admitted")
    task["intent_json"] = json.dumps(
        {"target": {"kind": "new_session", "directory": str(tmp_path)}}
    )

    async def unknown():
        return False

    with pytest.raises(DomainError, match="WRITE_UNKNOWN"):
        async with native.workspace_factory(
            None, task, {"id": "one"}, stopped=unknown
        ) as workspace:
            assert workspace["directory"] == str(tmp_path)


async def test_runtime_failure_is_exported_even_when_output_preexists(tmp_path):
    class Rejected:
        model = "fixture-rejected"

        async def stream(self, messages, tools):
            raise DomainError("MODEL_HTTP_401")
            yield ModelEvent("text", "unreachable")

    case = protocol_suite()["cases"][0]
    case["files"]["output.json"] = '{"sum":40}'
    result = await NativeFilesExecutor(Settings(), provider_factory=lambda *_: Rejected()).run(
        case, {}, tmp_path
    )
    assert not result["verified_delivery"]
    assert result["grade"]["reason"] in result["release_blockers"]


async def test_container_failure_zeroes_score_despite_correct_artifact(tmp_path, monkeypatch):
    from roami_agent.improvement import containers

    class Unused:
        model = "unused-fixture"

    async def docker(*args, **kwargs):
        if args[0] == "start":
            (tmp_path / "state" / "response.json").write_text(
                json.dumps({"output": "", "release_blockers": ["RSI_NATIVE_TASK_FAILED"]})
            )
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings(), provider_factory=lambda *_: Unused())
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    case = protocol_suite()["cases"][0]
    case["files"]["output.json"] = '{"sum":40}'
    result = await executor.run(case, {}, tmp_path)
    assert result["grade"]["artifact_assessment"]["passed"]
    assert result["grade"]["quality"] == 0
    assert not result["grade"]["passed"] and not result["grade"]["hard_passed"]
    assert not result["verified_delivery"]
