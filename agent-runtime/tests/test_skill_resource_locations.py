"""Skill resources are discoverable through admitted protocol reads, not file escape."""

import base64
import json
from pathlib import Path

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings

DATA = json.loads(
    Path(__file__).with_name("fixtures").joinpath("skill-resource-locations.json").read_text()
)


def call(path):
    return {"function": {"name": "read", "arguments": json.dumps({"path": path})}}


async def install(store, tmp_path, kind):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "skills"
    if kind == "configured":
        folder = root / DATA["name"]
        (folder / "references").mkdir(parents=True)
        (folder / "SKILL.md").write_text(DATA["entry"])
        (folder / DATA["referencePath"]).write_text(DATA["referenceText"])
        (folder / DATA["unaddressablePath"]).write_text(DATA["unaddressableText"])
        private = tmp_path / "private.md"
        private.write_text(DATA["privateText"])
        (folder / "references/outside.md").symlink_to(private)
    runtime = Runtime(
        store, ConversationModel(), settings=Settings(skill_roots=(root,), shell_roots=(workspace,))
    )
    if kind == "managed":
        files = {
            DATA["referencePath"]: DATA["referenceText"].encode(),
            DATA["scriptPath"]: DATA["scriptText"].encode(),
            DATA["unaddressablePath"]: DATA["unaddressableText"].encode(),
            DATA["binaryPath"]: b"\x00\xff",
        }
        await runtime.capability_imports.save(
            "local",
            "skills",
            {
                "name": DATA["name"],
                "text": DATA["entry"],
                "files": {name: base64.b64encode(body).decode() for name, body in files.items()},
            },
        )
    return runtime, {"workspace": {"directory": str(workspace)}}


@pytest.mark.parametrize("role", ["main", "worker", "research"])
@pytest.mark.parametrize("kind", ["configured", "managed"])
async def test_returned_resource_uri_reads_outside_workspace_without_file_access(
    store, tmp_path, role, kind
):
    runtime, binding = await install(store, tmp_path, kind)
    entry = await runtime.tools.invoke(call("skill://" + DATA["name"]), role, binding)
    package_path = str(Path(entry["packagePath"]) / DATA["referencePath"])
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await runtime.tools.invoke(call(package_path), role, binding)
    uri = "skill://" + DATA["name"] + "/" + DATA["referencePath"]
    assert uri in entry["resources"]
    assert DATA["referenceText"] not in entry["text"]
    assert not any(
        "outside.md" in item or "with space.md" in item or "sample.bin" in item
        for item in entry["resources"]
    )
    result = await runtime.tools.invoke(call(uri), role, binding)
    assert result["text"] == DATA["referenceText"]
    assert result["skillVersion"] == entry["version"]
    if kind == "managed":
        script_uri = "skill://" + DATA["name"] + "/" + DATA["scriptPath"]
        assert script_uri in entry["resources"]
        assert (await runtime.tools.invoke(call(script_uri), role, binding))["text"] == DATA[
            "scriptText"
        ]
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await runtime.tools.invoke(call(package_path), role, binding)


async def test_resource_locations_follow_current_managed_package_and_restart(store, tmp_path):
    runtime, binding = await install(store, tmp_path, "managed")
    before = await runtime.tools.invoke(call("skill://" + DATA["name"]), "worker", binding)
    path = "references/revised.md"
    await runtime.capability_imports.save(
        "local",
        "skills",
        {
            "name": DATA["name"],
            "text": DATA["entry"],
            "files": {path: base64.b64encode(b"Revised observations").decode()},
        },
        DATA["name"],
    )
    runtime = Runtime(store, ConversationModel(), settings=runtime.settings)
    after = await runtime.tools.invoke(call("skill://" + DATA["name"]), "worker", binding)
    assert after["version"] != before["version"]
    assert after["resources"] == ["skill://" + DATA["name"] + "/" + path]
    assert (await runtime.tools.invoke(call(after["resources"][0]), "worker", binding))[
        "text"
    ] == "Revised observations"
    with pytest.raises(DomainError, match="SKILL_REFERENCE_NOT_FOUND"):
        await runtime.tools.invoke(
            call("skill://" + DATA["name"] + "/" + DATA["referencePath"]), "worker", binding
        )


@pytest.mark.parametrize("disabled", ["skill", "read", "skill_read"])
async def test_resource_location_never_bypasses_disabled_skill_or_reader(store, tmp_path, disabled):
    runtime, binding = await install(store, tmp_path, "managed")
    entry = await runtime.tools.invoke(call("skill://" + DATA["name"]), "worker", binding)
    uri = "skill://" + DATA["name"] + "/" + DATA["referencePath"]
    assert uri in entry["resources"]
    if disabled == "skill":
        await runtime.capability_settings.save(
            "local", {"kind": "skills", "name": DATA["name"], "enabled": False}
        )
    else:
        runtime.tools.disabled_tools.add(disabled)
    with pytest.raises(DomainError, match="SKILL_DISABLED|TOOL_DISABLED"):
        await runtime.tools.invoke(call(uri), "worker", binding)
