"""Native requirements bind to saved Worker capabilities, including at execution."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_routing_policy import request, setup

from roami_agent.executors.native import NativeExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-105-mech-mc01/input/controls.json"
    ).read_text()
)


def configured(main, worker):
    settings = Settings(model_capabilities={"images": main})
    return replace(settings, worker_route=replace(settings.route("worker"), capabilities=worker))


@pytest.mark.parametrize("worker", CONTROLS["unavailable_worker_capabilities"])
async def test_main_image_support_does_not_admit_an_incapable_native_worker(store, worker):
    settings = configured(True, worker)
    runtime, targets, _, tools, binding = await setup(store, settings=settings)
    before = asdict(settings)
    try:
        args = request("bounded", requiredCapabilities=[CONTROLS["model_requirement"]])
        with pytest.raises(DomainError, match="ROUTING_CAPABILITY_UNAVAILABLE"):
            await tools.invoke(
                {"function": {"name": "delegate", "arguments": json.dumps(args)}},
                "main",
                binding,
            )
        assert not await store.call(lambda db: rows(db, "SELECT * FROM tasks"))
        assert not await store.call(
            lambda db: rows(db, "SELECT * FROM events WHERE kind='routing.decided'")
        )
        assert targets.catalog_calls == 0
        assert asdict(settings) == before
    finally:
        await runtime.close()


@pytest.mark.parametrize("main", CONTROLS["main_images"])
async def test_saved_worker_support_is_enough_without_switching_roles(store, main):
    settings = configured(main, {"images": True})
    runtime, _, router, _, binding = await setup(store, settings=settings)
    before = asdict(settings)
    try:
        decision = await router.decide(
            request("bounded", requiredCapabilities=[CONTROLS["model_requirement"]]), binding
        )
        assert decision["executor"] == "native"
        assert decision["capabilityVerification"] == "native_model_capabilities_observed"
        assert decision["metadataRefs"] == [
            {
                "kind": "native_model_capabilities",
                "role": "worker",
                "capabilities": {"images": True},
            }
        ]
        assert asdict(settings) == before
    finally:
        await runtime.close()


async def test_unknown_saved_model_capability_is_not_assumed_available(store):
    runtime, _, router, _, binding = await setup(store, settings=configured(True, {"images": True}))
    try:
        with pytest.raises(DomainError, match="ROUTING_CAPABILITY_UNAVAILABLE"):
            await router.decide(
                request("bounded", requiredCapabilities=[CONTROLS["unknown_model_requirement"]]),
                binding,
            )
    finally:
        await runtime.close()


async def test_native_model_and_node_command_requirements_are_both_observed(store):
    runtime, targets, router, _, binding = await setup(
        store, settings=configured(False, {"images": True})
    )
    original = targets.executors

    async def catalog(commands=None):
        value = await original()
        value["commandAvailability"] = {
            name: name == CONTROLS["known_cli"] for name in commands or []
        }
        return value

    targets.executors = catalog
    try:
        args = request(
            "bounded",
            requiredCapabilities=["cli:" + CONTROLS["known_cli"], CONTROLS["model_requirement"]],
        )
        decision = await router.decide(args, binding)
        assert decision["metadataRefs"][0]["commandAvailability"] == {"renderer": True}
        assert decision["metadataRefs"][1]["capabilities"] == {"images": True}
        binding["toolCallId"] = "missing-renderer"
        args["routing"]["requiredCapabilities"][0] = "cli:" + CONTROLS["missing_cli"]
        with pytest.raises(DomainError, match="ROUTING_CAPABILITY_UNAVAILABLE"):
            await router.decide(args, binding)
    finally:
        await runtime.close()


@pytest.mark.parametrize("requirement", [[], [CONTROLS["model_requirement"]]])
async def test_execution_rechecks_saved_support_and_keeps_legacy_tasks_compatible(requirement):
    calls = []

    async def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return "Completed"

    async def database_call(*args, **kwargs):
        return None

    executor = NativeExecutor(
        execute,
        SimpleNamespace(call=database_call),
        configured(True, {"images": False}),
    )
    task = {
        "id": "owned-task",
        "owner_id": "alice",
        "budget_json": "{}",
        "intent_json": json.dumps(
            {
                "target": {"kind": "new_session", "resourceOnly": True},
                "routingDecision": {
                    "requiredCapabilities": requirement,
                    "capabilityVerification": "native_model_capabilities_observed",
                },
            }
        ),
    }
    run = {"id": "owned-run", "native_branch_id": "owned-branch"}
    turn = {"id": "owned-turn", "branch_id": "owned-branch"}
    if requirement:
        with pytest.raises(DomainError, match="ROUTING_CAPABILITY_UNAVAILABLE"):
            await executor.run(task, run, turn=turn)
        assert not calls
    else:
        result = await executor.run(task, run, turn=turn)
        assert result["state"] == "succeeded" and len(calls) == 1
