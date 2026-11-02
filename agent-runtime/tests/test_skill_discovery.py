"""Optional Skill metadata is visible before discovery; instructions stay lazy."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.server.configuration import Settings


def read_description(runtime, role="main"):
    return next(
        (
            item["function"]["description"]
            for item in runtime.tools.catalog(role)
            if item["function"]["name"] == "read"
        ),
        "",
    )


def contracts(runtime):
    return {
        role: {
            item["function"]["name"]: item["function"]["parameters"]
            for item in runtime.tools.catalog(role)
        }
        for role in ("main", "worker", "research")
    }


@pytest.mark.parametrize("role", ["main", "worker", "research"])
async def test_configured_skill_metadata_precedes_explicit_instruction_read(store, tmp_path, role):
    root = tmp_path / "skills"
    folder = root / "sensor-workflow"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: sensor-workflow\ndescription: Prepare sensor reports\n---\n"
        "Deferred instructions: load the station reference before processing."
    )
    (folder / "scripts/read.py").write_text("print('RESOURCE_NOT_IN_DISCOVERY')")
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    description = read_description(runtime, role)
    assert "sensor-workflow" in description
    assert "Prepare sensor reports" in description
    assert "skill://sensor-workflow" in description
    assert "Deferred instructions" not in description
    assert "RESOURCE_NOT_IN_DISCOVERY" not in description
    assert str(folder) not in description
    result = await runtime.tools.invoke(
        {
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": "skill://sensor-workflow"}),
            }
        },
        role,
        {},
    )
    assert "Deferred instructions" in result["text"]


async def test_managed_skill_discovery_tracks_import_update_disable_and_remove(store):
    runtime = Runtime(store, ConversationModel())
    initial = read_description(runtime)
    schemas = contracts(runtime)
    value = {
        "name": "report-workflow",
        "description": "Prepare sensor reports",
        "text": "DEFERRED_BODY",
    }
    await runtime.capability_imports.save("local", "skills", value)
    assert "Prepare sensor reports" in read_description(runtime)
    assert "skill://report-workflow" in read_description(runtime)
    assert "DEFERRED_BODY" not in read_description(runtime)
    assert contracts(runtime) == schemas
    await runtime.capability_imports.save(
        "local", "skills", {**value, "description": "Review station readings"}, name=value["name"]
    )
    assert "Review station readings" in read_description(runtime)
    assert "Prepare sensor reports" not in read_description(runtime)
    for enabled in (False, True):
        await runtime.capability_settings.save(
            "local", {"kind": "skills", "name": value["name"], "enabled": enabled}
        )
        for role in ("main", "worker", "research"):
            assert ("report-workflow" in read_description(runtime, role)) is enabled
    await runtime.capability_imports.save("local", "skills", None, name=value["name"], remove=True)
    assert read_description(runtime) == initial
    assert contracts(runtime) == schemas


@pytest.mark.parametrize("tool", ["read", "skill_read"])
async def test_unreadable_skills_are_absent_from_discovery(store, tool):
    runtime = Runtime(store, ConversationModel())
    await runtime.capability_imports.save(
        "local",
        "skills",
        {"name": "report-workflow", "description": "Prepare reports", "text": "Overview"},
    )
    runtime.tools.disabled_tools.add(tool)
    assert "report-workflow" not in read_description(runtime)
    assert runtime.tools.directory.list(kind="skill")["items"] == []
