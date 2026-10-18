"""Routing uses current CLI identity, bounded metadata and explicit ambiguity errors."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.executors import targets
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def test_project_discovery_pages_stable_ids_and_discards_unrelated_fields(monkeypatch):
    calls = []

    async def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {
                    "data": {
                        "projects": [
                            {"key": f"id-{i}", "name": "Expenses", "tail": "private log"}
                            for i in range(25, -1, -1)
                        ]
                    }
                }
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(Settings(cli_bin="/selected/roami"))
    first = await directory.search("project", "expenses", limit=10)
    second = await directory.search("project", "expenses", offset=first["nextOffset"], limit=20)
    assert first["total"] == 26 and len(first["items"]) == 10
    assert second["nextOffset"] is None and len(second["items"]) == 16
    assert {v["projectId"] for v in first["items"] + second["items"]} == {
        f"id-{i}" for i in range(26)
    }
    assert all(v["kind"] == "project" for v in first["items"])
    assert "private log" not in json.dumps(first)
    assert calls[0] == (
        ["/selected/roami", "project", "ls", "--json"],
        {
            "timeout": 5,
            "excluded_env": {
                "ROAMI_AGENT_API_KEY",
                "ROAMI_AGENT_SAVED_MAIN_KEY",
                "ROAMI_AGENT_SAVED_WORKER_KEY",
            },
        },
    )


async def test_live_sessions_preserve_duplicate_labels_without_selecting_one(monkeypatch):
    calls = []

    async def execute(argv, **kwargs):
        calls.append(argv)
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                [{"id": f"stable-{i}", "label": "同名", "state": "live"} for i in range(2)]
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    result = await TargetDirectory(Settings()).search("session", "同名")
    assert result["total"] == 2
    assert {v["sessionId"] for v in result["items"]} == {"stable-0", "stable-1"}
    assert calls[0][1:] == ["session", "ls", "--live", "--json"]


async def test_resolution_uses_strict_cli_and_sanitizes_diagnostics(monkeypatch):
    calls = []
    diagnostics = "SESSION_TARGET_AMBIGUOUS"

    async def execute(argv, **kwargs):
        calls.append(argv)
        return {"exitCode": 1, "stderr": diagnostics}

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(Settings())
    with pytest.raises(DomainError, match="SESSION_TARGET_AMBIGUOUS"):
        await directory.resolve("session", "duplicate label")
    assert calls[0][1:] == ["session", "resolve", "duplicate label", "--strict", "--json"]
    diagnostics = "authentication failed; private account details"
    with pytest.raises(DomainError, match="^TARGET_DISCOVERY_UNAVAILABLE$"):
        await directory.resolve("project", "project-id")


async def test_invalid_receipts_fail_instead_of_reporting_an_empty_catalog(monkeypatch):
    payload = {"data": {"projects": "invalid"}}

    async def execute(argv, **kwargs):
        return {"exitCode": 0, "stdout": json.dumps(payload)}

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(Settings())
    with pytest.raises(DomainError, match="INVALID_TARGET_RECEIPT"):
        await directory.search("project")
    payload = {"data": {"projects": [{"key": "id", "name": None}]}}
    with pytest.raises(DomainError, match="INVALID_TARGET_RECEIPT"):
        await directory.search("project")
    payload = []
    with pytest.raises(DomainError, match="INVALID_TARGET_RECEIPT"):
        await directory.resolve("session", "id")


async def test_lookup_failure_and_output_budget_are_bounded(monkeypatch):
    async def execute(argv, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(Settings())
    with pytest.raises(DomainError, match="TARGET_DISCOVERY_UNAVAILABLE"):
        await directory.search("session")

    async def large(argv, **kwargs):
        return {
            "exitCode": 0,
            "stdout": json.dumps([{"id": str(i), "label": "测" * 160} for i in range(30)]),
        }

    monkeypatch.setattr(targets, "execute", large)
    result = await directory.search("session", limit=20)
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 6200
    assert 0 < result["nextOffset"] < 20


async def test_main_routes_discovered_project_through_persisted_tool_result(store, monkeypatch):
    from test_runtime import until

    observed = []

    async def execute(argv, **kwargs):
        observed.append(argv)
        return {
            "exitCode": 0,
            "stdout": json.dumps({"data": {"projects": [{"key": "expenses-id", "name": "记账"}]}}),
        }

    class Model:
        model = "injected-routing-model"

        async def stream(self, messages, catalog):
            latest = messages[-1]
            if latest["content"] == "给记账项目安排工作":
                name, args = "target_search", {"kind": "project", "query": "记账"}
            elif latest["role"] == "tool" and json.loads(latest["content"]).get("items"):
                item = json.loads(latest["content"])["items"][0]
                name, args = (
                    "delegate",
                    {"goal": "Update expenses", "executor": "codex", "target": item},
                )
            else:
                yield ModelEvent("text", "已安排，任务在后台准备。")
                return
            yield ModelEvent(
                "tool",
                {"id": name, "function": {"name": name, "arguments": json.dumps(args)}},
            )

    monkeypatch.setattr(targets, "execute", execute)
    runtime = Runtime(store, Model())
    # Drive only the Main turn; no real coding session is messaged or created.
    c = await runtime.conversations.create("alice")
    reply = await runtime.chat.submit("alice", c["id"], "route", "给记账项目安排工作")
    await runtime.start()
    try:
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (reply["turnId"],)
            ),
        )
        tasks = await runtime.tasks.list("alice", c["id"])
        assert len(tasks) == 1
        assert json.loads(tasks[0]["intent_json"])["target"]["projectId"] == "expenses-id"
        assert observed[0][1:] == ["project", "ls", "--json"]
        results = await store.call(
            lambda db: db.execute(
                "SELECT count(*) FROM tool_calls WHERE tool_name='target_search' AND state='succeeded'"
            ).fetchone()[0]
        )
        assert results == 1
    finally:
        await runtime.close()


async def test_overview_uses_full_cli_counts_and_distinguishes_dormant_and_loose(monkeypatch):
    calls = []

    async def execute(argv, **kwargs):
        calls.append(argv)
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {
                    "data": {
                        "projects": [
                            {
                                "key": "one",
                                "name": "One",
                                "sessions": 8,
                                "dormant": 2,
                                "top": [{"tail": "private output"}],
                            },
                            {
                                "key": "two",
                                "name": "Two",
                                "sessions": 0,
                                "dormant": 0,
                                "archived": True,
                            },
                        ],
                        "loose": [{"state": "live"}, {"state": "dormant"}],
                    }
                }
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    result = await TargetDirectory(Settings()).overview()
    assert result == {
        "scope": "current_node",
        "projects": 2,
        "archivedProjects": 1,
        "projectSessions": 8,
        "looseSessions": 2,
        "sessions": 10,
        "liveSessions": 7,
        "dormantSessions": 3,
    }
    assert len(calls) == 1
    assert "private output" not in json.dumps(result)


@pytest.mark.parametrize(
    "data",
    [
        {"projects": [], "loose": None},
        {"projects": [{"key": "id", "name": "Name", "sessions": 1, "dormant": 2}], "loose": []},
        {"projects": [{"key": "id", "name": "Name", "sessions": True, "dormant": 0}], "loose": []},
    ],
)
async def test_overview_rejects_incomplete_or_invalid_counts(monkeypatch, data):
    async def execute(argv, **kwargs):
        return {"exitCode": 0, "stdout": json.dumps({"data": data})}

    monkeypatch.setattr(targets, "execute", execute)
    with pytest.raises(DomainError, match="INVALID_TARGET_RECEIPT"):
        await TargetDirectory(Settings()).overview()


async def test_cli_auth_error_is_actionable_without_exposing_response_details(monkeypatch):
    async def execute(argv, **kwargs):
        return {
            "exitCode": 1,
            "stdout": json.dumps(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "private login detail",
                    }
                }
            ),
            "stderr": "",
        }

    monkeypatch.setattr(targets, "execute", execute)
    with pytest.raises(DomainError, match="^ROAMI_CLI_AUTH_REQUIRED$"):
        await TargetDirectory(Settings()).overview()


async def test_project_sessions_use_complete_cli_membership_not_top_three(monkeypatch):
    calls = []

    async def execute(argv, **kwargs):
        calls.append(argv)
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {
                    "data": {
                        "projectId": "p",
                        "sessions": [
                            {"name": f"session-{i}", "label": f"Task {i}", "agent": "codex"}
                            for i in range(6)
                        ]
                        + [{"name": "sleeping", "state": "dormant"}],
                    }
                }
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    result = await TargetDirectory(Settings()).search("session", project_id="p")
    assert result["total"] == 6
    assert result["items"][-1] == {
        "kind": "session",
        "sessionId": "session-5",
        "label": "Task 5",
        "state": "live",
        "projectId": "p",
        "executor": "codex",
    }
    assert calls == [["roami", "project", "sessions", "p", "--json"]]


async def test_dispatch_skill_is_available_to_main_in_installed_package(store):
    from test_runtime import ConversationModel

    runtime = Runtime(store, ConversationModel())
    catalog = runtime.tools.catalog(role="main")
    assert {"read", "tool_search"} <= {tool["function"]["name"] for tool in catalog}
    loaded = await runtime.tools.registry["skill_read"].handler({"name": "roami-dispatch"}, {})
    assert loaded["version"] and "nextOffset" in loaded["text"] and "session_send" in loaded["text"]
