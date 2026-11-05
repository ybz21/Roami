"""The native evaluator preserves user-authorized continuation and profile identity."""

import json
import sqlite3
from pathlib import Path

import pytest

from roami_agent.improvement.evaluation.execution.executors import (
    NativeFilesExecutor,
    ProtocolFixtureModel,
)
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.tools.command_families import COMMANDS

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-106-mech-nt01/input/controls.json"
    ).read_text()
)


@pytest.fixture
def container_constructor(monkeypatch):
    # Only the constructor is simulated; no shell or container command is run.
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: path == Path("/.dockerenv") or exists(path))
    monkeypatch.setenv("ROAMI_RSI_CONTAINER", "1")


def test_execution_permissions_have_distinct_cache_identities(container_constructor):
    settings = Settings()
    profiles = [(p["allow_shell"], p["allow_tasks"]) for p in CONTROLS["profiles"]]
    hashes = [
        NativeFilesExecutor(settings, allow_shell=shell, allow_tasks=tasks).model_hash
        for shell, tasks in profiles
    ]
    assert len(set(hashes)) == len(profiles)


async def test_native_user_followup_reuses_the_task_and_workspace(tmp_path, container_constructor):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = CONTROLS["first_prompt"]
    followup = CONTROLS["followup_prompt"]

    def tool(name, arguments, ident):
        return ModelEvent(
            "tool", {"id": ident, "function": {"name": name, "arguments": json.dumps(arguments)}}
        )

    def results(messages):
        return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]

    class Main:
        model = "native-main-control"

        async def stream(self, messages, tools):
            names = {t["function"]["name"] for t in tools}
            assert not names & {"write", "edit", "file_write", "file_patch"}
            users = [m["content"] for m in messages if m["role"] == "user"]
            current = users[-1] if users else ""
            completed = any(
                isinstance(m.get("content"), str) and "Executor evidence:" in m["content"]
                for m in messages
            )
            if completed:
                yield tool(
                    "reply", {"text": "The worker returned its file for acceptance."}, "reply"
                )
            elif followup in current:
                if "bash" not in names:
                    yield tool(
                        "reply", {"text": "The continuation operation is unavailable."}, "reply"
                    )
                else:
                    listed = next(
                        (v for v in reversed(results(messages)) if isinstance(v, list)), None
                    )
                    if listed:
                        yield tool(
                            "bash",
                            {
                                "argv": [
                                    "roami",
                                    *COMMANDS["task_steer"],
                                    "--input",
                                    json.dumps(
                                        {
                                            "taskId": listed[0]["id"],
                                            "revision": listed[0]["revision"],
                                            "text": followup,
                                            "sourceQuote": followup,
                                            "requestComplete": True,
                                        }
                                    ),
                                ]
                            },
                            "continue",
                        )
                    else:
                        yield tool(
                            "bash",
                            {"argv": ["roami", *COMMANDS["task_status"], "--input", "{}"]},
                            "discover",
                        )
            else:
                yield tool(
                    "delegate",
                    {
                        "goal": first,
                        "requestComplete": True,
                        "target": {"kind": "new_session", "directory": str(workspace)},
                        "routing": {
                            "explicitExecutor": None,
                            "complexity": "bounded",
                            "complexityBasis": {"procedure": "Write one supplied literal"},
                            "routingExplanation": "Use the provided workspace and verify the file",
                        },
                    },
                    "create",
                )
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    class Worker:
        model = "native-worker-control"

        async def stream(self, messages, tools):
            users = [m["content"] for m in messages if m["role"] == "user"]
            updating = any(followup in str(value) for value in users)
            boundary = max(i for i, m in enumerate(messages) if m["role"] == "user")
            current = messages[boundary + 1 :]
            values = results(current)
            written = any(
                m.get("role") == "tool"
                and m.get("tool_call_id") in {"write-new", "update"}
                and "error" not in json.loads(m["content"])
                for m in current
            )
            if written:
                yield ModelEvent("text", "Saved result.json.")
            elif updating:
                read = next(
                    (v for v in reversed(values) if isinstance(v, dict) and v.get("sha256")),
                    None,
                )
                if read:
                    yield tool(
                        "write",
                        {
                            "path": CONTROLS["filename"],
                            "expectedSha256": read["sha256"],
                            "content": json.dumps(CONTROLS["final_value"]),
                        },
                        "update",
                    )
                else:
                    yield tool("read", {"path": CONTROLS["filename"]}, "read-existing")
            else:
                yield tool(
                    "write",
                    {
                        "path": CONTROLS["filename"],
                        "expectedSha256": None,
                        "content": json.dumps(CONTROLS["first_value"]),
                    },
                    "write-new",
                )
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    main, worker = Main(), Worker()
    executor = NativeFilesExecutor(
        Settings(),
        allow_shell=True,
        allow_tasks=True,
        settle_maintenance=True,
        workspace=workspace,
        provider_factory=lambda settings, role: (
            main if role == "main" else worker if role == "worker" else ProtocolFixtureModel()
        ),
    )
    root = tmp_path / "run"
    root.mkdir()
    case = {
        "id": "native-continuation-control",
        "prompt": first,
        "followups": [followup],
        "files": {},
        "limits": {"seconds": 10},
        "counts_as_delivery": True,
        "judge": {
            "kind": "json",
            "path": CONTROLS["filename"],
            "expected": CONTROLS["final_value"],
        },
    }
    result = await executor.run(case, {}, root)
    assert json.loads((workspace / CONTROLS["filename"]).read_text()) == CONTROLS["final_value"]
    log = json.loads((root / "execution-log.json").read_text())
    assert len(log["tasks"]) == 1 and log["tasks"][0]["revision"] == 2
    assert len(log["native_execution"]) == 1
    assert log["native_execution"][0]["executor_kind"] == "native"
    with sqlite3.connect((root / "runtime.db").as_uri() + "?mode=ro", uri=True) as db:
        workspaces = [
            json.loads(r[0])["workspace"]
            for r in db.execute(
                "SELECT payload_json FROM events WHERE kind='task.workspace_prepared'"
            )
        ]
    assert len(workspaces) == 2
    assert len({item["workspaceId"] for item in workspaces}) == 1
    assert {item["directory"] for item in workspaces} == {str(workspace)}
    assert result["grade"]["passed"] and not result["release_blockers"]
