"""Configured Skills retain their local scripts, assets and dependency layout."""

import json
import sys
from pathlib import Path

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def read_skill(name):
    return {"function": {"name": "read", "arguments": json.dumps({"path": f"skill://{name}"})}}


@pytest.mark.parametrize("role", ["main", "worker", "research"])
async def test_local_package_script_uses_adjacent_assets_without_import(store, tmp_path, role):
    root = tmp_path / "local skills"
    package = root / "asset-reader"
    (package / "scripts").mkdir(parents=True)
    (package / "assets").mkdir()
    (package / "SKILL.md").write_text("---\nname: asset-reader\n---\nUse scripts/read_asset.py")
    (package / "assets/source.bin").write_bytes(b"\x00\xffsource")
    script = package / "scripts/read_asset.py"
    script.write_text(
        "from pathlib import Path\n"
        "print((Path(__file__).resolve().parents[1] / 'assets/source.bin').read_bytes().hex())\n"
    )
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    result = await runtime.tools.invoke(read_skill("asset-reader"), role, {})
    assert Path(result["packagePath"]) == package.resolve()
    assert "00ff736f75726365" not in result["text"]
    output = await runtime.tools.invoke(
        {
            "function": {
                "name": "bash",
                "arguments": json.dumps(
                    {
                        "argv": [
                            sys.executable,
                            str(Path(result["packagePath"], "scripts/read_asset.py")),
                        ]
                    }
                ),
            }
        },
        role,
        {"workspace": {"directory": str(tmp_path)}},
    )
    assert output["exitCode"] == 0
    assert output["stdout"].strip() == "00ff736f75726365"
    assert not runtime.capability_imports.saved["skills"]
    assert not (tmp_path / "agents/capability-packages").exists()
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "asset-reader", "enabled": False}
    )
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await runtime.tools.invoke(read_skill("asset-reader"), role, {})


async def test_configured_skill_symlink_cannot_advertise_outside_package(store, tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("---\nname: outside\n---\nPrivate package")
    (root / "outside").symlink_to(outside, target_is_directory=True)
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    assert "outside" not in runtime.tools.skills
    builtin = await runtime.tools.invoke(read_skill("roami"), "main", {})
    assert "packagePath" not in builtin
