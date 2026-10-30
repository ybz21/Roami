"""The evaluation lane waits for native work without fabricating task acceptance."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation.execution.evaluation_tasks import (
    bind_evaluation_tasks,
    settle_evaluation_tasks,
    verify_native_execution,
)
from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
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
        assert (await verify_native_execution(store))[0]["executor_kind"] == "native"
    finally:
        await runtime.close()


async def test_task_lane_rejects_foreign_workspace_and_unknown_writes(tmp_path):
    native = SimpleNamespace()
    runtime = SimpleNamespace(
        dispatch=SimpleNamespace(native_executor=native),
        tools=SimpleNamespace(registry={"bash": SimpleNamespace(main=True)}),
    )
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


@pytest.mark.parametrize("name", ["bash", "shell"])
@pytest.mark.parametrize("scope", ["host", "workspace"])
async def test_evaluation_main_cannot_execute_shell_but_worker_can(store, tmp_path, name, scope):
    runtime = Runtime(
        store, SimpleNamespace(model="unused"), settings=Settings(shell_roots=(tmp_path,))
    )
    bind_evaluation_tasks(runtime, tmp_path)
    try:
        assert "bash" not in {t["function"]["name"] for t in runtime.tools.catalog("main")}
        assert "bash" in {t["function"]["name"] for t in runtime.tools.catalog("worker")}
        call = {
            "function": {
                "name": name,
                "arguments": json.dumps({"argv": ["touch", "main-started"], "scope": scope}),
            }
        }
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(call, "main", {"owner": "owner"})
        assert not (tmp_path / "main-started").exists()
        call["function"]["arguments"] = json.dumps(
            {"argv": ["touch", "worker-started"], "scope": "workspace"}
        )
        result = await runtime.tools.invoke(
            call, "worker", {"owner": "owner", "workspace": {"directory": str(tmp_path)}}
        )
        assert result["exitCode"] == 0 and (tmp_path / "worker-started").is_file()
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "fault,error",
    [
        (None, None),
        ("no_task", "RSI_NATIVE_TASK_REQUIRED"),
        ("foreign_executor", "RSI_NATIVE_EXECUTOR_REQUIRED"),
        ("stale_revision", "RSI_NATIVE_EXECUTOR_REQUIRED"),
        ("running_attempt", "RSI_NATIVE_TASK_INCOMPLETE"),
        ("queued_task", "RSI_NATIVE_TASK_INCOMPLETE"),
        ("newer_failed_attempt", "RSI_NATIVE_TASK_INCOMPLETE"),
    ],
)
async def test_native_execution_requires_current_successful_attempt(store, fault, error):
    from test_routing_policy import setup
    from test_task_delivery_benchmark import admit, mark

    runtime, _, _, _, binding = await setup(store)
    try:
        if fault != "no_task":
            task = await admit(runtime, binding, "Deliver required files", "native-proof")
            await mark(runtime, task, "waiting_user", {"state": "succeeded"})

            def alter(db):
                if fault == "foreign_executor":
                    db.execute("UPDATE task_attempts SET executor_kind='cli'")
                elif fault == "stale_revision":
                    db.execute("UPDATE tasks SET revision=revision+1")
                elif fault == "running_attempt":
                    db.execute("UPDATE task_attempts SET state='running'")
                elif fault == "queued_task":
                    db.execute("UPDATE tasks SET state='queued'")
                elif fault == "newer_failed_attempt":
                    attempt = dict(db.execute("SELECT * FROM task_attempts").fetchone())
                    attempt.update(
                        id="newer-attempt", launch_id="newer-launch", attempt_no=2, state="failed"
                    )
                    db.execute(
                        "INSERT INTO task_attempts ("
                        + ",".join(attempt)
                        + ") VALUES ("
                        + ",".join("?" for _ in attempt)
                        + ")",
                        tuple(attempt.values()),
                    )

            await store.call(alter, write=True)
        if error:
            with pytest.raises(DomainError, match=error):
                await verify_native_execution(store)
        else:
            proof = await verify_native_execution(store)
            assert len(proof) == 1 and proof[0]["attempt_state"] == "succeeded"
    finally:
        await runtime.close()


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


@pytest.mark.parametrize(
    "blocker,reason",
    [
        ("RSI_NATIVE_TASK_FAILED", "RSI_RUNTIME_REPORTED_FAILURE"),
        ("RSI_TOKEN_BUDGET", "RSI_TOKEN_BUDGET"),
        ("RSI_NATIVE_TASK_REQUIRED", "RSI_NATIVE_TASK_REQUIRED"),
        ("RSI_NATIVE_EXECUTOR_REQUIRED", "RSI_NATIVE_EXECUTOR_REQUIRED"),
        ("RSI_NATIVE_TASK_INCOMPLETE", "RSI_NATIVE_TASK_INCOMPLETE"),
        ("private arbitrary error text", "RSI_RUNTIME_REPORTED_FAILURE"),
    ],
)
async def test_container_failure_zeroes_score_despite_correct_artifact(
    tmp_path, monkeypatch, blocker, reason
):
    from roami_agent.improvement.evaluation.execution import containers

    class Unused:
        model = "unused-fixture"

    async def docker(*args, **kwargs):
        if args[0] == "start":
            (tmp_path / "state" / "response.json").write_text(
                json.dumps({"output": "", "release_blockers": [blocker]})
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
    assert result["grade"]["reason"] == reason


@pytest.mark.parametrize(
    "summary,current,expected",
    [
        ("RSI_TOKEN_BUDGET", True, "RSI_TOKEN_BUDGET"),
        ("RSI_TIME_BUDGET", True, "RSI_TIME_BUDGET"),
        ("RSI_USAGE_UNKNOWN", True, "RSI_USAGE_UNKNOWN"),
        ("RSI_REQUEST_BUDGET", True, "RSI_REQUEST_BUDGET"),
        ("private error text", True, "RSI_NATIVE_TASK_FAILED"),
        (["RSI_TOKEN_BUDGET"], True, "RSI_NATIVE_TASK_FAILED"),
        ("RSI_TOKEN_BUDGET", False, "RSI_NATIVE_TASK_FAILED"),
    ],
)
async def test_native_failure_preserves_only_current_attempt_budget_codes(
    store, summary, current, expected
):
    from test_routing_policy import setup
    from test_task_delivery_benchmark import admit, mark

    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Save output", "budget")
        await mark(runtime, task, result={"state": "failed", "summary": summary})
        if not current:
            await store.call(
                lambda db: db.execute(
                    "UPDATE tasks SET revision=revision+1 WHERE id=?", (task["id"],)
                ),
                write=True,
            )
        with pytest.raises(DomainError) as failure:
            await settle_evaluation_tasks(store)
        assert failure.value.code == expected
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "code,expected",
    [
        ("RSI_TOKEN_BUDGET", "RSI_TOKEN_BUDGET"),
        ("RSI_REQUEST_BUDGET", "RSI_REQUEST_BUDGET"),
        ("RSI_TIME_BUDGET", "RSI_TIME_BUDGET"),
        ("RSI_USAGE_UNKNOWN", "RSI_USAGE_UNKNOWN"),
        ("MODEL_HTTP_401", "RSI_TURN_FAILED"),
        ("private arbitrary error text", "RSI_TURN_FAILED"),
    ],
)
async def test_main_failure_preserves_only_budget_codes(tmp_path, code, expected):
    from roami_agent.improvement.integrations.measurements import BudgetAdmissionRejected

    class Rejected:
        model = "fixture-admission"

        async def stream(self, messages, tools):
            raise BudgetAdmissionRejected(code)
            yield ModelEvent("text", "unreachable")

    case = protocol_suite()["cases"][0]
    case["files"]["output.json"] = '{"sum":40}'
    result = await NativeFilesExecutor(Settings(), provider_factory=lambda *_: Rejected()).run(
        case, {}, tmp_path
    )
    assert result["grade"]["reason"] == expected
    assert expected in result["release_blockers"]
    assert not result["verified_delivery"] and not result["grade"]["passed"]


async def test_turn_failure_ignores_other_turns_conversations_and_event_kinds(store):
    from roami_agent.improvement.evaluation.execution.evaluation_tasks import (
        evaluation_turn_failure,
    )
    from roami_agent.storage.database import event

    runtime = Runtime(store, SimpleNamespace(model="unused"))
    first = await runtime.conversations.create("owner")
    second = await runtime.conversations.create("other")
    one = await runtime.conversations.accept("owner", first["id"], "one", "First")
    two = await runtime.conversations.accept("owner", first["id"], "two", "Second")
    current = {"id": one["turnId"], "conversation_id": first["id"], "state": "failed"}

    def write(db):
        for conversation, turn, kind in [
            (first["id"], two["turnId"], "turn.failed"),
            (second["id"], one["turnId"], "turn.failed"),
            (first["id"], one["turnId"], "turn.interrupted"),
        ]:
            event(db, conversation, kind, {"error": "RSI_TOKEN_BUDGET"}, turn_id=turn)

    try:
        await store.call(write, write=True)
        assert await evaluation_turn_failure(store, current) == "RSI_TURN_FAILED"
    finally:
        await runtime.close()


@pytest.mark.parametrize("shared", [False, True])
async def test_container_request_preserves_the_shared_daily_policy(tmp_path, monkeypatch, shared):
    from roami_agent.improvement.evaluation.execution import containers

    class Unused:
        model = "unused-fixture"

    async def docker(*args, **kwargs):
        if args[0] == "start":
            request = json.loads((tmp_path / "state/request.json").read_text())
            assert request.get("shared_daily_limit", False) is True
            (tmp_path / "state/response.json").write_text(
                json.dumps({"output": "", "release_blockers": []})
            )
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(
        Settings(), provider_factory=lambda *_: Unused(), shared_daily_limit=shared
    )
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    case = protocol_suite()["cases"][0]
    case["files"]["output.json"] = '{"sum":40}'
    result = await executor.run(case, {}, tmp_path)
    assert result["grade"]["hard_passed"]


@pytest.mark.parametrize("shared", [None, False, True])
async def test_container_entry_uses_the_host_spending_policy(tmp_path, monkeypatch, shared):
    from pathlib import Path

    from roami_agent.improvement.evaluation.execution import container_agent

    state = tmp_path / "state"
    state.mkdir()
    request = {"case": {"limits": {"seconds": 10}}, "policy": {}}
    if shared is not None:
        request["shared_daily_limit"] = shared
    if shared is True:
        from roami_agent.improvement.evaluation.execution.container_context import model_context

        request["model_context"] = model_context(Settings())
    (state / "request.json").write_text(json.dumps(request))
    captured = {}

    def path(value):
        value = str(value)
        return (
            tmp_path / value.lstrip("/")
            if value.startswith(("/state", "/workspace"))
            else Path(value)
        )

    path.home = lambda: tmp_path / "home"

    class Executor:
        def __init__(self, settings, **kwargs):
            captured.update(kwargs)

        async def run(self, case, policy, root):
            return {"release_blockers": []}

    monkeypatch.setattr(container_agent, "Path", path)
    monkeypatch.setattr(container_agent, "NativeFilesExecutor", Executor)
    await container_agent.main()
    assert captured.get("shared_daily_limit", False) is (shared is True)
    assert (state / "response.json").is_file()


async def test_native_evaluation_profile_exposes_delivery_writes_only_to_workers(store, tmp_path):
    runtime = Runtime(store, SimpleNamespace(model="profile-fixture"))
    names = {"bash", "write", "edit", "file_write", "file_patch"}
    before = {item["function"]["name"] for item in runtime.tools.catalog("worker")}
    bind_evaluation_tasks(runtime, tmp_path)
    main = {item["function"]["name"] for item in runtime.tools.catalog("main")}
    worker = {item["function"]["name"] for item in runtime.tools.catalog("worker")}
    assert not main & names
    assert worker & names == before & names
    assert {"bash", "write", "edit"} <= worker
    assert "delegate" in main and "read" in main


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("version", [None, "1", "2", "3", "4", "5", "6"])
async def test_shared_daily_preflight_rejects_legacy_images_before_execution(
    tmp_path, monkeypatch, shared, version
):
    from roami_agent.improvement.evaluation.execution import containers

    async def docker(*args, **kwargs):
        assert args[:2] == ("image", "inspect")
        labels = {"org.roami.rsi.shared-daily-policy": version} if version else None
        return json.dumps([{"Id": "fixture-image", "Config": {"Labels": labels}}]).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings(), shared_daily_limit=shared)
    if version != "6":
        with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
            await executor.preflight()
        assert executor.image_id is None
    else:
        assert (await executor.preflight())["image_id"] == "fixture-image"


@pytest.mark.parametrize("host_unknown", [False, True])
@pytest.mark.parametrize("runtime_failure", [False, True])
async def test_shared_container_usage_gap_is_not_an_execution_failure(
    tmp_path, monkeypatch, host_unknown, runtime_failure
):
    from roami_agent.improvement.evaluation.execution import containers

    class Unused:
        model = "unused-fixture"

    class Budget(containers.EpisodeBudget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.unknown = host_unknown

    async def docker(*args, **kwargs):
        if args[0] == "start":
            blockers = ["unknown_provider_usage"]
            if runtime_failure:
                blockers.append("RSI_NATIVE_TASK_INCOMPLETE")
            (tmp_path / "state" / "response.json").write_text(
                json.dumps({"output": "", "release_blockers": blockers})
            )
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "EpisodeBudget", Budget)
    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(
        Settings(), provider_factory=lambda *_: Unused(), shared_daily_limit=True
    )
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    case = protocol_suite()["cases"][0]
    case["files"]["output.json"] = '{"sum":40}'
    result = await executor.run(case, {}, tmp_path)
    if host_unknown and not runtime_failure:
        assert result["grade"]["passed"]
        assert result["verified_delivery"] == case["counts_as_delivery"]
        assert result["metrics"]["tokens"] is None
        assert result["release_blockers"] == ["unknown_provider_usage"]
    else:
        assert not result["grade"]["passed"] and not result["verified_delivery"]
        assert result["grade"]["reason"] == (
            "RSI_NATIVE_TASK_INCOMPLETE" if runtime_failure else "RSI_RUNTIME_REPORTED_FAILURE"
        )
