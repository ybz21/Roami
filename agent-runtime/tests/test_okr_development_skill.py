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
        source = Path(__file__).parents[1] / "src/roami_agent/skills/okr-development"

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
