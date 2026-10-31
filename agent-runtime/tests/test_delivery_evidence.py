"""Usable files and explicit log requests survive without inventing missing outputs."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_routing_policy import setup
from test_runtime import ConversationModel, until
from test_task_delivery_benchmark import admit, mark

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row

DATA = json.loads((Path(__file__).parent / "fixtures/delivery-evidence.json").read_text())


async def completed_delivery(
    store, tmp_path, *, capture=False, explicit=False, mention_input=False
):
    workspace = tmp_path / "workspace"
    (workspace / "materials").mkdir(parents=True)
    source = workspace / "materials" / DATA["input_name"]
    source.write_text(DATA["input_content"])

    class Main:
        model = "delivery-evidence-main"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "Report ready.")

    class Worker:
        model = "delivery-evidence-worker"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                script = (
                    "from pathlib import Path; import sys; "
                    "Path('output').mkdir(); "
                    f"Path({DATA['output_path']!r}).write_text({DATA['output_content']!r}); "
                    f"sys.stdout.write('x'*{DATA['capture_bytes'] if capture else 0})"
                )
                yield ModelEvent(
                    "tool",
                    {
                        "id": "write-report",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps({"argv": [sys.executable, "-c", script]}),
                        },
                    },
                )
                return
            summary = f"[Report]({DATA['output_path']})"
            if mention_input:
                summary = f"Compared `{DATA['input_name']}`. " + summary
            if explicit:
                captures = await runtime.artifacts.list("alice", task_id=task["id"])
                log = next(a for a in captures if a["metadata"].get("source") == "shell")
                summary += f" Requested log: [trace]({log['downloadUrl']})"
            yield ModelEvent("text", summary)

    @asynccontextmanager
    async def prepared(*args, **kwargs):
        yield {"workspaceId": "delivery-fixture", "directory": str(workspace)}

    async def verifier(task, result):
        return (workspace / DATA["output_path"]).read_text() == DATA["output_content"]

    runtime = Runtime(
        store, Main(), worker_model=Worker(), memory_model=ConversationModel(), verifier=verifier
    )
    runtime.dispatch.native_executor.workspace_factory = prepared
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Create output/report.txt from supplied material",
            key="delivery-evidence",
            record_intent=True,
            target={"kind": "new_session", "directory": str(workspace)},
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                (conversation["id"],),
            ),
        )
        result = json.loads(
            (
                await store.call(
                    lambda db: row(
                        db,
                        "SELECT result_json FROM task_attempts WHERE task_id=?",
                        (task["id"],),
                    )
                )
            )["result_json"]
        )
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        retained = await runtime.artifacts.list("alice", task_id=task["id"])
        assert source.read_text() == DATA["input_content"]
        assert (workspace / DATA["output_path"]).read_text() == DATA["output_content"]
        return result, messages[-1]["content"]["text"], retained
    finally:
        await runtime.close()


async def test_inline_input_basename_does_not_invent_a_missing_output(store, tmp_path):
    result, _, retained = await completed_delivery(store, tmp_path, mention_input=True)
    assert result.get("unavailableOutputs", []) == []
    assert [a["name"] for a in result["artifactRefs"]] == ["report.txt"]
    assert [a["name"] for a in retained] == ["report.txt"]


async def test_process_capture_is_retained_without_becoming_an_unrequested_attachment(
    store, tmp_path
):
    result, text, retained = await completed_delivery(store, tmp_path, capture=True)
    assert {a["name"] for a in retained} == {"report.txt", "shell-stdout.txt"}
    assert [a["name"] for a in result["artifactRefs"]] == ["report.txt"]
    assert "shell-stdout.txt" not in text
    assert result["artifactRefs"][0]["downloadUrl"] in text


async def test_requested_log_is_downloadable_after_the_prioritized_deliverable(store, tmp_path):
    result, text, retained = await completed_delivery(store, tmp_path, capture=True, explicit=True)
    assert [a["name"] for a in result["artifactRefs"]] == ["report.txt", "shell-stdout.txt"]
    urls = [a["downloadUrl"] for a in result["artifactRefs"]]
    assert all(url in text for url in urls) and text.index(urls[0]) < text.index(urls[1])
    assert len(retained) == 2


@pytest.mark.parametrize(
    "reference,unavailable",
    [
        ("incidental", False),
        ("link", True),
        ("scoped", True),
        ("absolute", True),
        ("missing_root", True),
        ("symlink", True),
        ("hidden", True),
        ("traversal", True),
    ],
)
async def test_explicit_missing_outputs_and_workspace_failures_stay_visible(
    store, tmp_path, reference, unavailable
):
    runtime, _, _, _, binding = await setup(store)
    root = tmp_path / "workspace"
    if reference != "missing_root":
        root.mkdir()
    name = "missing.txt"
    summary = f"Referenced `{name}`."
    if reference == "link":
        summary = f"[Requested report]({name})"
    elif reference == "scoped":
        name = "output/missing.txt"
        summary = f"Output: `{name}`"
    elif reference == "absolute":
        name = str(root / name)
        summary = f"Output: `{name}`"
    elif reference == "symlink":
        name = "linked.txt"
        target = tmp_path / "outside.txt"
        target.write_text("private")
        (root / name).symlink_to(target)
        summary = f"Output: `{name}`"
    elif reference == "hidden":
        name = ".hidden.txt"
        summary = f"Output: `{name}`"
    elif reference == "traversal":
        name = "../outside.txt"
        (tmp_path / "outside.txt").write_text("private")
        summary = f"Output: `{name}`"
    try:
        task = await admit(
            runtime, binding, "Deliver the requested report", "missing", executor="codex"
        )
        await mark(
            runtime,
            task,
            "waiting_user",
            {"state": "succeeded", "summary": summary, "workspace": {"directory": str(root)}},
        )
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == "waiting_user"
        assert not detail["delivery"]["artifacts"]
        assert bool(detail["delivery"]["unavailable"]) == unavailable
        if unavailable:
            assert detail["delivery"]["unavailable"][0]["sourcePath"] == name
    finally:
        await runtime.close()
