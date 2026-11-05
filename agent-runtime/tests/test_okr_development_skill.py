import hashlib
import json
from pathlib import Path

from test_runtime import ConversationModel

from roami_agent.app import Runtime


async def test_okr_development_skill_is_available_before_any_project_exists(store):
    runtime = Runtime(store, ConversationModel())
    try:
        catalog = runtime.tools.directory.list("okr-development", "skill")
        assert any(item["name"] == "okr-development" for item in catalog["items"])
        source = Path(__file__).parents[2] / "skills/okr-development"

        async def read(path):
            return await runtime.tools.invoke(
                {"function": {"name": "read", "arguments": json.dumps({"path": path})}},
                "main",
                {},
            )

        skill = await read("skill://okr-development")
        assert skill["text"] == (source / "SKILL.md").read_text()
        reference = await read("skill://okr-development/references/bundle.md")
        assert reference["text"] == (source / "references/bundle.md").read_text()
        assert reference["version"] == hashlib.sha256(reference["text"].encode()).hexdigest()
        assert reference["skillVersion"] == skill["version"]
        assert (
            await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0
        )
        assert await runtime.swarms.list("alice") == []
    finally:
        await runtime.close()


async def test_generic_template_and_composable_parts_are_readable_without_execution(store):
    runtime = Runtime(store, ConversationModel())
    try:

        async def read(path):
            return await runtime.tools.invoke(
                {"function": {"name": "read", "arguments": json.dumps({"path": path})}},
                "main",
                {},
            )

        skill = await read("skill://okr-development")
        resource = "assets/.roami/okr/okr.json"
        assert "skill://okr-development/" + resource in skill["resources"]
        config = await read("skill://okr-development/" + resource)
        assert json.loads(config["text"])["objective"] == "{{objective}}"
        assert config["skillVersion"] == skill["version"]
        source = await read(
            "skill://okr-development/parts/connectors/github/scripts/fetch_github.py"
        )
        assert source["skillVersion"] == skill["version"]
        assert (
            await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0
        )
        assert await runtime.swarms.list("alice") == []
    finally:
        await runtime.close()


def test_skill_manifest_includes_complete_templates_with_exact_bytes():
    source = Path(__file__).parents[2] / "skills/okr-development"
    declared = {}
    for line in (source / "package.files").read_text().splitlines():
        digest, path = line.split()
        assert path not in declared
        assert hashlib.sha256((source / path).read_bytes()).hexdigest() == digest
        declared[path] = digest
    actual = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and path.name != "package.files" and "__pycache__" not in path.parts
    }
    assert set(declared) == actual
    assert "assets/AGENTS.md" in declared
    assert "assets/.roami/okr/agents/team.json" in declared
    assert "assets/.roami/okr/data/observations.jsonl" in declared
    assert "assets/.roami/okr/state/current.json" not in declared
