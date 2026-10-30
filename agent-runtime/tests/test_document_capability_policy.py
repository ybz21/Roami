"""Automatic input preparation must obey the same capability policy as explicit reads."""

import hashlib
from contextlib import asynccontextmanager

import pytest
from test_presentation_reads import presentation_bytes
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent


def disable_document_capability(tools, name):
    if name == "presentation_files":
        tools.disabled_skills = {name}
    else:
        tools.disabled_tools = {name}


@pytest.mark.parametrize("disabled", ["read", "file_read", "skill_read", "presentation_files"])
async def test_native_intake_obeys_execution_capability_policy(
    store, tmp_path, monkeypatch, disabled
):
    source = tmp_path / "deck.pptx"
    body = presentation_bytes()
    source.write_bytes(body)
    captured, snapshots = [], []

    class Worker:
        model = "document-capability-contract"

        async def stream(self, messages, tools):
            captured.append(messages)
            yield ModelEvent("text", "Inspection availability recorded; no changes.")

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "policy-contract", "directory": str(tmp_path)}

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    runtime.dispatch.native_executor.workspace_factory = prepare
    original = runtime.files.snapshot

    async def snapshot(*args, **kwargs):
        snapshots.append(args[0])
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.files, "snapshot", snapshot)
    disable_document_capability(runtime.tools, disabled)
    # Exercise the existing execution gate, independently of the intake projection.
    call = {"function": {"name": "read", "arguments": '{"path":"deck.pptx"}'}}
    if disabled in {"skill_read", "presentation_files"}:
        call["function"]["arguments"] = '{"path":"skill://presentation_files"}'
    with pytest.raises(DomainError, match="TOOL_DISABLED|SKILL_DISABLED"):
        await runtime.tools.invoke(
            call, "worker", {"taskId": "policy", "workspace": {"directory": str(tmp_path)}}
        )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Inspect deck.pptx",
            key="policy",
            target={"kind": "new_session", "directory": str(tmp_path)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(store, lambda db: bool(captured))
        prompt = captured[0]
        has_snapshot = any(
            isinstance(m.get("content"), str)
            and m["content"].startswith("Read-only document snapshots")
            for m in prompt
        )
        assert not any(
            "Applicable built-in document workflow:" in m.get("content", "") for m in prompt
        )
        if disabled in {"read", "file_read"}:
            assert snapshots == []
            assert not has_snapshot
            assert not any(hashlib.sha256(body).hexdigest() in m.get("content", "") for m in prompt)
        else:
            assert snapshots == ["deck.pptx"]
            assert has_snapshot
        assert source.read_bytes() == body
    finally:
        await runtime.close()


@pytest.mark.parametrize("disabled", ["read", "file_read", "skill_read", "presentation_files"])
async def test_next_worker_prompt_drops_input_or_workflow_after_policy_changes(
    store, tmp_path, disabled
):
    source = tmp_path / "deck.pptx"
    source.write_bytes(presentation_bytes())
    captured = []

    class Worker:
        model = "document-policy-change-contract"

        async def stream(self, messages, tools):
            captured.append(messages)
            if len(captured) == 1:
                disable_document_capability(runtime.tools, disabled)
                yield ModelEvent(
                    "tool",
                    {
                        "id": "policy-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": '{"path":"deck.pptx"}'},
                    },
                )
            else:
                yield ModelEvent("text", "Capability change respected; no edits.")

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "policy-change", "directory": str(tmp_path)}

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Inspect deck.pptx",
            key="policy-change",
            target={"kind": "new_session", "directory": str(tmp_path)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(store, lambda db: len(captured) >= 2)
        first, second = captured[:2]
        assert any("Applicable built-in document workflow:" in m.get("content", "") for m in first)
        assert any("Read-only document snapshots" in m.get("content", "") for m in first)
        assert not any(
            "Applicable built-in document workflow:" in m.get("content", "") for m in second
        )
        if disabled in {"read", "file_read"}:
            assert not any("Read-only document snapshots" in m.get("content", "") for m in second)
        else:
            assert any("Read-only document snapshots" in m.get("content", "") for m in second)
    finally:
        await runtime.close()


@pytest.mark.parametrize("disabled", ["read", "file_read"])
async def test_intake_stops_remaining_reads_when_policy_changes_during_io(
    store, tmp_path, monkeypatch, disabled
):
    body = presentation_bytes()
    for name in ["first.pptx", "second.pptx"]:
        (tmp_path / name).write_bytes(body)
    runtime = Runtime(store, ConversationModel())
    observed = []
    original = runtime.files.snapshot

    async def snapshot(*args, **kwargs):
        observed.append(args[0])
        result = await original(*args, **kwargs)
        disable_document_capability(runtime.tools, disabled)
        return result

    monkeypatch.setattr(runtime.files, "snapshot", snapshot)
    try:
        result = await runtime.document_intake.prepare(
            "Inspect first.pptx and second.pptx",
            {"taskId": "policy", "workspace": {"directory": str(tmp_path)}},
        )
        assert result == {}
        assert observed == ["first.pptx"]
        assert all((tmp_path / name).read_bytes() == body for name in ["first.pptx", "second.pptx"])
        # A replaced policy set must take effect without recreating the intake.
        runtime.tools.disabled_tools = set()
        monkeypatch.setattr(runtime.files, "snapshot", original)
        allowed = await runtime.document_intake.prepare(
            "Inspect second.pptx",
            {"taskId": "policy", "workspace": {"directory": str(tmp_path)}},
        )
        assert [item["path"] for item in allowed["sources"]] == ["second.pptx"]
    finally:
        await runtime.close()
