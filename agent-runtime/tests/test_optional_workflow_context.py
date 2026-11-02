"""Installed workflows guide persisted role policies without preloading their bodies."""

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import request_basis
from roami_agent.server.configuration import Settings


def configuration(runtime, role="main"):
    turn = {} if role == "main" else {"executionRunId": "native-attempt"}
    instructions = (
        runtime.settings.main_instructions
        if role == "main"
        else runtime.settings.worker_instructions
    )
    return runtime.loop.context._configuration(turn, instructions, runtime.tools.catalog(role))


@pytest.mark.parametrize("role", ["main", "worker", "research"])
async def test_persisted_policy_gets_workflow_guidance_before_execution(store, role):
    settings = Settings(
        main_instructions="Persisted Main policy", worker_instructions="Persisted Worker policy"
    )
    runtime = Runtime(store, ConversationModel(), settings=settings)
    await runtime.capability_imports.save(
        "local",
        "skills",
        {
            "name": "station-workflow",
            "description": "Process station records",
            "text": "BODY_LOADED_ONLY_BY_EXPLICIT_READ",
        },
    )
    result = configuration(runtime, role)
    assert "Installed optional workflows" in result["instructions"]
    assert "before choosing operations" in result["instructions"]
    assert "station-workflow" in result["instructions"]
    assert "Process station records" in result["instructions"]
    assert "skill://station-workflow" in result["instructions"]
    assert "BODY_LOADED_ONLY_BY_EXPLICIT_READ" not in str(result)
    assert "station-workflow" in str(result["catalog"])
    assert result["instructions"].startswith(
        "Persisted Main policy" if role == "main" else "Persisted Worker policy"
    )
    assert settings.main_instructions == "Persisted Main policy"
    assert settings.worker_instructions == "Persisted Worker policy"


async def test_context_and_compaction_follow_import_disable_and_remove(store):
    runtime = Runtime(store, ConversationModel())
    initial = configuration(runtime)
    assert "Installed optional workflows" not in initial["instructions"]
    await runtime.capability_imports.save(
        "local",
        "skills",
        {
            "name": "station-workflow",
            "description": "Process station records",
            "text": "Deferred body",
        },
    )
    active = configuration(runtime)
    assert "Installed optional workflows" in active["instructions"]
    assert "station-workflow" in active["instructions"]
    assert runtime.context.request_context() == active
    assert request_basis(initial) != request_basis(active)
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "station-workflow", "enabled": False}
    )
    assert configuration(runtime) == initial
    assert runtime.context.request_context() == initial
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "station-workflow", "enabled": True}
    )
    assert configuration(runtime) == active
    await runtime.capability_imports.save(
        "local", "skills", None, name="station-workflow", remove=True
    )
    assert configuration(runtime) == initial


@pytest.mark.parametrize("tool", ["read", "skill_read"])
async def test_unreadable_workflows_do_not_add_guidance(store, tool):
    runtime = Runtime(store, ConversationModel())
    await runtime.capability_imports.save(
        "local",
        "skills",
        {"name": "station-workflow", "description": "Process records", "text": "Deferred body"},
    )
    runtime.tools.disabled_tools.add(tool)
    for role in ("main", "worker", "research"):
        assert "Installed optional workflows" not in configuration(runtime, role)["instructions"]
