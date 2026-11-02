"""An external CSV exporter runs through normal Worker tools and durable delivery."""

import base64
import copy
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


def foundations(runtime):
    contract = copy.deepcopy(runtime.tools.catalog("worker"))
    for item in contract:
        if item["function"]["name"] == "read":
            item["function"].pop("description")
    return contract


async def test_optional_csv_package_executes_and_persists_delivery(store, tmp_path):
    repository = Path(__file__).resolve().parents[3]
    package = repository / "skills/tabular-analysis"
    case = repository / "cases/case-69-mech-tb01"
    workspace = tmp_path / "table work"
    workspace.mkdir()
    for name in ["raw.csv", "analysis.csv"]:
        (workspace / name).write_bytes((case / "input" / name).read_bytes())
    source = {name: (workspace / name).read_bytes() for name in ["raw.csv", "analysis.csv"]}

    class Main:
        model = "table-contract-main"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "text",
                "Exported 2 records with source columns, identifiers and precision preserved; analysis columns excluded. The file awaits acceptance.",
            )

    class Worker:
        model = "table-contract-worker"

        async def stream(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not receipts:
                name, args = "read", {"path": "skill://tabular-analysis"}
            elif len(receipts) == 3:
                first, second = [json.loads(r["stdout"]) for r in receipts[1:]]
                spec = {
                    "source": "raw.csv",
                    "analysis": "analysis.csv",
                    "destination": "cleaned.csv",
                    "expectedSourceSha256": first["sha256"],
                    "expectedAnalysisSha256": second["sha256"],
                    "keys": ["date"],
                    "dateKeys": ["date"],
                    "values": "source",
                    "numeric": ["unit count", "value"],
                }
                name, args = (
                    "bash",
                    {
                        "argv": [
                            sys.executable,
                            "-c",
                            "import pathlib,sys; pathlib.Path(sys.argv[1]).open('x').write(sys.argv[2])",
                            str(workspace / "export.json"),
                            json.dumps(spec),
                        ]
                    },
                )
            elif len(receipts) < 6:
                script = str(Path(receipts[0]["packagePath"]) / "scripts/csv_export.py")
                if len(receipts) == 4:
                    operation = ["export", "--spec", "export.json"]
                else:
                    filename = {1: "raw.csv", 2: "analysis.csv", 5: "cleaned.csv"}[len(receipts)]
                    operation = ["inspect", "--path", filename]
                name, args = (
                    "bash",
                    {"argv": [sys.executable, script, *operation, "--workspace", str(workspace)]},
                )
            else:
                checked = json.loads(receipts[-1]["stdout"])
                assert checked["rows"] == 2 and checked["columns"] == [
                    "record id",
                    "date",
                    "unit count",
                    "value",
                ]
                yield ModelEvent("text", "已导出2条，保留源字段与标识：[cleaned.csv](cleaned.csv)")
                return
            yield ModelEvent(
                "tool",
                {
                    "id": str(len(receipts)),
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "table-contract", "directory": str(workspace)}

    runtime = Runtime(store, Main(), worker_model=Worker(), memory_model=Main())
    runtime.dispatch.native_executor.workspace_factory = prepare
    before, names = foundations(runtime), set(runtime.tools.registry)
    text = (package / "SKILL.md").read_text()
    await runtime.capability_imports.save(
        "local",
        "skills",
        {
            "name": "tabular-analysis",
            "description": text.split("description: ", 1)[1].split("\n", 1)[0],
            "text": text,
            "files": {
                str(f.relative_to(package)): base64.b64encode(f.read_bytes()).decode()
                for f in (package / "scripts").glob("*.py")
            },
        },
    )
    assert foundations(runtime) == before and set(runtime.tools.registry) == names
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Use the external CSV Skill to select the analysis rows and export source values to cleaned.csv.",
            key="table-contract",
            target={"kind": "new_session", "directory": str(workspace)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                (conversation["id"],),
            ),
        )
        refs = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(refs) == 1 and refs[0]["name"] == "cleaned.csv"
        expected = (case / "expected" / "cleaned.csv").read_bytes()
        assert (await runtime.artifacts.read("alice", refs[0]["id"]))[1] == expected
        assert all((workspace / name).read_bytes() == body for name, body in source.items())
        (workspace / "cleaned.csv").unlink()
        assert (await runtime.artifacts.read("alice", refs[0]["id"]))[1] == expected
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await runtime.artifacts.read("bob", refs[0]["id"])
        await runtime.capability_imports.save(
            "local", "skills", None, name="tabular-analysis", remove=True
        )
        assert "tabular-analysis" not in runtime.tools.skills
        assert foundations(runtime) == before and set(runtime.tools.registry) == names
    finally:
        await runtime.close()
