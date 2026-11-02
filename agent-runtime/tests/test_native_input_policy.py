"""Native tasks load files and optional workflows only through explicit generic tools."""

import json
from contextlib import asynccontextmanager

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def tool(name, args, ident):
    return ModelEvent(
        "tool", {"id": ident, "function": {"name": name, "arguments": json.dumps(args)}}
    )


async def run_native(runtime, store, workspace, goal):
    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "input-policy", "directory": str(workspace)}

    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    conversation = await runtime.conversations.create("alice")
    await runtime.tasks.create(
        "alice",
        conversation["id"],
        goal,
        key="input-policy",
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


@pytest.mark.parametrize("filename", ["input.pptx", "input.pdf", "input.bin"])
async def test_native_preparation_never_reads_named_inputs_implicitly(
    store, tmp_path, monkeypatch, filename
):
    body = b"private input, not a runtime instruction"
    (tmp_path / filename).write_bytes(body)
    captured, reads = [], []

    class Worker:
        model = "input-policy-protocol-fixture"

        async def stream(self, messages, tools):
            captured.append(messages)
            yield ModelEvent("text", "No file inspection requested by this fixture.")

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    original = runtime.files.read

    async def observe(*args, **kwargs):
        reads.append(args[0])
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.files, "read", observe)
    try:
        await run_native(runtime, store, tmp_path, f"Inspect {filename}")
        assert reads == []
        assert captured and not any(m["role"] == "tool" for m in captured[0])
        assert not any(body.decode() in str(m.get("content", "")) for m in captured[0])
        assert (tmp_path / filename).read_bytes() == body
    finally:
        await runtime.close()


@pytest.mark.parametrize("disabled", ["read", "file_read"])
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_explicit_file_reads_obey_current_policy(
    store, tmp_path, monkeypatch, disabled, phase
):
    (tmp_path / "input.bin").write_bytes(b"observed data")
    reads, replies = [], []

    class Worker:
        model = "explicit-file-policy-fixture"

        async def stream(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not receipts:
                yield tool("read", {"path": "input.bin"}, "first")
            elif phase == "after" and len(receipts) == 1:
                runtime.tools.disabled_tools.add(disabled)
                yield tool("read", {"path": "input.bin"}, "second")
            else:
                replies.extend(receipts)
                yield ModelEvent("text", "Current execution policy checked.")

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    original = runtime.files.read

    async def observe(*args, **kwargs):
        reads.append(args[0])
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.files, "read", observe)
    if phase == "before":
        runtime.tools.disabled_tools.add(disabled)
    try:
        await run_native(runtime, store, tmp_path, "Inspect input.bin")
        assert len(reads) == (1 if phase == "after" else 0)
        assert replies[-1]["error"] == "TOOL_DISABLED"
        if phase == "after":
            assert replies[0]["data"] == "observed data"
    finally:
        await runtime.close()


@pytest.mark.parametrize("disabled", ["skill_read", "workflow"])
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_explicit_skill_reads_obey_current_policy(store, tmp_path, disabled, phase):
    root = tmp_path / "skills"
    folder = root / "workflow"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: Optional workflow\n---\nCurrent workflow v2"
    )
    replies, initial = [], []

    def disable():
        if disabled == "workflow":
            runtime.tools.disabled_skills.add(disabled)
        else:
            runtime.tools.disabled_tools.add(disabled)

    class Worker:
        model = "explicit-skill-policy-fixture"

        async def stream(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not receipts:
                initial.extend(messages)
                yield tool("read", {"path": "skill://workflow"}, "first")
            elif phase == "after" and len(receipts) == 1:
                disable()
                yield tool("read", {"path": "skill://workflow"}, "second")
            else:
                replies.extend(receipts)
                yield ModelEvent("text", "Current workflow policy checked.")

    runtime = Runtime(
        store, ConversationModel(), worker_model=Worker(), settings=Settings(skill_roots=(root,))
    )
    if phase == "before":
        disable()
    try:
        await run_native(runtime, store, tmp_path, "Use the optional workflow.")
        assert not any("Current workflow v2" in str(m.get("content", "")) for m in initial)
        assert replies[-1]["error"] == (
            "SKILL_DISABLED" if disabled == "workflow" else "TOOL_DISABLED"
        )
        if phase == "after":
            assert "Current workflow v2" in replies[0]["text"]
        if disabled == "workflow":
            assert not runtime.tools.directory.list("workflow", "skill")["items"]
    finally:
        await runtime.close()
