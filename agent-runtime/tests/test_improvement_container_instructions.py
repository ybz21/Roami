"""Saved role policies survive the private Actor configuration boundary."""

import json
from dataclasses import replace

import pytest
from test_improvement_container_context import captured_request, configured
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.execution.container_agent import container_settings
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize(
    "policies", [("保存的主指令\nexact Main", "保存的后台指令\nexact Worker"), ("", "")]
)
async def test_saved_policies_reach_actor_request_context(store, tmp_path, monkeypatch, policies):
    host = replace(configured(), main_instructions=policies[0], worker_instructions=policies[1])
    request = await captured_request(host, tmp_path, monkeypatch)
    child = container_settings(request)
    assert (child.main_instructions, child.worker_instructions) == policies
    assert request["role_instructions"] == {"main": policies[0], "worker": policies[1]}
    runtime = Runtime(store, ConversationModel(), settings=child)
    try:
        for role, instructions in zip(("main", "worker"), policies):
            actual = child.main_instructions if role == "main" else child.worker_instructions
            turn = {} if role == "main" else {"executionRunId": "native-attempt"}
            context = runtime.loop.context._configuration(turn, actual, runtime.tools.catalog(role))
            assert context["instructions"].startswith(instructions + "\nImage input availability")
            assert f"Current role: {role}" in context["instructions"]
        assert runtime.context.request_context()["instructions"].startswith(
            policies[0] + "\nImage input availability"
        )
    finally:
        await runtime.close()
    for private in [
        "private.invalid",
        "private-main",
        "private-worker",
        "PRIVATE_KEY",
        "reasoning_effort",
    ]:
        assert private not in json.dumps(request)


@pytest.mark.parametrize("label", [None, "", "0", "2", "1"])
async def test_model_actor_requires_role_instruction_support_before_start(monkeypatch, label):
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        labels = {"org.roami.rsi.shared-daily-policy": "6"}
        if label is not None:
            labels["org.roami.rsi.role-instructions"] = label
        return json.dumps([{"Id": "fixture-image", "Config": {"Labels": labels}}]).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings(main_instructions="Saved Main"))
    if label == "1":
        assert (await executor.preflight())["image_id"] == "fixture-image"
    else:
        with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
            await executor.preflight()
        assert executor.image_id is None
    assert calls == [("image", "inspect", executor.image)]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"main": "x"},
        {"main": True, "worker": "x"},
        {"main": "x", "worker": []},
        {"main": "x", "worker": "y", "endpoint": "private"},
    ],
)
def test_invalid_role_policies_are_not_silently_replaced(raw):
    with pytest.raises(DomainError, match="RSI_CONTAINER_ROLE_INSTRUCTIONS_INVALID"):
        container_settings({"role_instructions": raw})


def test_legacy_request_without_role_policies_keeps_original_defaults():
    child = container_settings({})
    assert child.main_instructions == Settings().main_instructions
    assert child.worker_instructions == Settings().worker_instructions


@pytest.mark.parametrize("field", ["main_instructions", "worker_instructions"])
def test_saved_policy_changes_invalidate_actor_model_fingerprint(field):
    before = Settings()
    after = replace(before, **{field: "Changed saved policy"})
    assert (
        containers.ContainerExecutor(before).model_hash
        != containers.ContainerExecutor(after).model_hash
    )
