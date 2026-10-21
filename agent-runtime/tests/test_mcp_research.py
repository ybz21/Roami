"""Read-only research discovers real MCP tools and verifies their returned sources."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_foundations import call, cli
from test_runtime import ConversationModel, until
from test_web_research import MemoryModel

from roami_agent.app import Runtime
from roami_agent.dispatch.web_evidence import retrieved_sources
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

URL = "https://source.example/news?a=1&b=2"


def server_config(tmp_path):
    return {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("search_mcp_fixture.py")), str(tmp_path)],
        "read_only": ["search"],
    }


@pytest.mark.parametrize(
    "browser_fails,query", [(False, "news"), (True, "news"), (False, "no-sources")]
)
async def test_research_discovers_mcp_without_workspace_and_verifies_sources(
    store, tmp_path, browser_fails, query
):
    class Worker:
        model = "mcp-research"
        stage = 0

        async def stream(self, messages, tools):
            self.stage += 1
            if self.stage == 1:
                wire = call("tool_list", {"kind": "mcp"})
            elif self.stage == 2:
                result = json.loads(messages[-1]["content"])
                assert [item["name"] for item in result["items"]] == ["mcp_discover"]
                wire = cli("mcp_discover", {"server": "search"})
            elif self.stage == 3:
                discovered = json.loads(messages[-1]["content"])["catalog"]["items"]
                search = next(item for item in discovered if "_search_" in item["name"])
                assert search["inputSchema"]["required"] == ["query"]
                assert not any("publish" in item["name"] for item in discovered)
                wire = call("tool_list", {"kind": "mcp"})
            elif self.stage == 4:
                result = json.loads(messages[-1]["content"])
                assert not any("publish" in item["name"] for item in result["items"])
                self.search = next(
                    item["name"] for item in result["items"] if "_search_" in item["name"]
                )
                wire = (
                    cli("browser_open", {"url": URL})
                    if browser_fails
                    else cli(self.search, {"query": query})
                )
            elif self.stage == 5 and browser_fails:
                result = json.loads(messages[-1]["content"])
                assert result["executionStarted"] is False
                assert "MCP" in result["recovery"]
                wire = cli(self.search, {"query": query})
            else:
                yield ModelEvent("text", "Market news: " + URL)
                return
            wire["id"] = "step-" + str(self.stage)
            yield ModelEvent("tool", wire)

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=Worker(),
        memory_model=MemoryModel(),
        settings=Settings(
            browser={"enabled": browser_fails},
            mcp_servers={"search": server_config(tmp_path)},
        ),
    )
    commands = []

    async def offline(argv, **options):
        commands.append(argv[2])
        return {"exitCode": 1, "stdout": "", "stderr": "Connection refused"}

    @asynccontextmanager
    async def forbidden_workspace(*args, **kwargs):
        pytest.fail("MCP research must not allocate a shell workspace")
        yield

    runtime.browser.runner = offline
    runtime.dispatch.native_executor.workspace_factory = forbidden_workspace
    try:
        assert (await runtime.tools.registry["capability_overview"].handler({}, {}))[
            "webResearchAvailable"
        ]
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Find public market news",
            key="mcp-research",
            target={"kind": "new_session", "resourceOnly": True},
            record_intent=True,
        )
        await runtime.start()
        expected = "failed" if query == "no-sources" else "succeeded"
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state=?", (task["id"], expected)
            ),
            timeout=15,
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        completion = await store.call(
            lambda db: row(
                db,
                "SELECT payload_json FROM events WHERE task_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                (task["id"], "task." + expected),
            )
        )
        result = json.loads(completion["payload_json"])["result"]
        if expected == "succeeded":
            assert result["verification"]["kind"] == "web_retrieval"
            source = result["verification"]["sources"][0]
            assert (
                source["url"] == URL
                and source["kind"] == "mcp"
                and source["retrievedMs"] >= run["started_ms"]
            )
            assert not await store.call(
                lambda db: retrieved_sources(db, task, {**run, "id": "another-attempt"}, URL)
            )
            assert not await store.call(
                lambda db: retrieved_sources(db, task, run, "https://invented.example/")
            )
        else:
            assert result["errorCode"] == "WEB_RETRIEVAL_EVIDENCE_MISSING"
        assert (tmp_path / "searched").read_text() == query
        assert not (tmp_path / "published").exists()
        assert commands == (["capabilities"] if browser_fails else [])
        publish = next(name for name in runtime.tools.registry if "_publish_" in name)
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(cli(publish, {"text": "do not publish"}), "research", {})
        search = next(name for name in runtime.tools.registry if "_search_search_" in name)
        await runtime.capability_settings.save(
            "local", {"kind": "tools", "name": search, "enabled": False}
        )
        assert search not in {
            item["name"]
            for item in runtime.tools.directory.list(kind="mcp", role="research")["items"]
        }
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await runtime.tools.invoke(cli(search, {"query": "news"}), "research", {})
    finally:
        await runtime.close()
