import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def read(path):
    return {"function": {"name": "read", "arguments": json.dumps({"path": path})}}


async def test_reference_is_loaded_on_demand_and_changes_catalog_version(store, tmp_path):
    root = tmp_path / "skills"
    folder = root / "cli-guide"
    references = folder / "references"
    references.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: cli-guide\ndescription: CLI guide\n---\nOverview")
    document = references / "commands.md"
    document.write_text("First reference")
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    initial = runtime.tools.directory.list("cli-guide", "skill")["catalogVersion"]
    overview = await runtime.tools.invoke(read("skill://cli-guide"), "main", {})
    assert "First reference" not in overview["text"]
    result = await runtime.tools.invoke(
        read("skill://cli-guide/references/commands.md"), "main", {}
    )
    assert result["text"] == "First reference"
    assert result["skillVersion"] == overview["version"]
    document.write_text("Updated reference")
    recreated = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    assert initial != recreated.tools.directory.list("cli-guide", "skill")["catalogVersion"]
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "cli-guide", "enabled": False}
    )
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await runtime.tools.invoke(read("skill://cli-guide/references/commands.md"), "main", {})


async def test_reference_cannot_escape_skill_or_bypass_research_profile(store, tmp_path):
    root = tmp_path / "skills"
    folder = root / "cli-guide"
    references = folder / "references"
    references.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: cli-guide\n---\nOverview")
    secret = tmp_path / "private.md"
    secret.write_text("not a skill document")
    (references / "outside.md").symlink_to(secret)
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    for path in (
        "skill://cli-guide/references/outside.md",
        "skill://cli-guide/references/missing.md",
        "skill://cli-guide/../private.md",
    ):
        with pytest.raises(DomainError):
            await runtime.tools.invoke(read(path), "main", {})
    with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
        await runtime.tools.invoke(
            read("skill://roami-dispatch/references/chrome.md"), "research", {}
        )
    assert any(
        item["name"] == "roami-dispatch"
        for item in runtime.tools.directory.list("截图", "skill")["items"]
    )
    assert (
        "roami chrome"
        in (
            await runtime.tools.invoke(
                read("skill://roami-dispatch/references/chrome.md"), "main", {}
            )
        )["text"]
    )
