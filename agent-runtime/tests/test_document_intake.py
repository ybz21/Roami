"""Explicit task documents reach the first Worker request through the normal file boundary."""

import hashlib
import io
import json
import zipfile
from contextlib import asynccontextmanager

import pytest
from test_compaction_threshold import SummaryModel
from test_presentation_reads import presentation_bytes
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.context.document_intake import TaskDocumentIntake, requested_presentations
from roami_agent.context.projection import Context
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.conversation.transcript import Conversations
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row
from roami_agent.storage.workspace_files import WorkspaceFiles
from roami_agent.tools.registry import Tools


def document_tools(text=""):
    tools = Tools()
    tools.skills["presentation_files"] = {"text": text}
    return tools


@pytest.mark.parametrize(
    "text,paths",
    [
        (
            'Inspect "folder/deck with spaces.pptx" and save result.pptx.',
            ["folder/deck with spaces.pptx", "result.pptx"],
        ),
        ("Read `/workspace/deck.PPTX`, then /workspace/deck.PPTX.", ["/workspace/deck.PPTX"]),
        (
            "Read ../outside.pptx but not input.pptx.bak or https://remote.invalid/deck.pptx",
            ["../outside.pptx"],
        ),
        ("Answer the question without files.", []),
    ],
)
def test_only_explicit_local_presentation_references_are_candidates(text, paths):
    assert requested_presentations(text) == paths


async def test_intake_observes_only_named_existing_files_and_never_rewrites_them(tmp_path):
    source = tmp_path / "deck.pptx"
    original = presentation_bytes()
    source.write_bytes(original)
    (tmp_path / "unmentioned.pptx").write_bytes(b"unrelated")
    files = WorkspaceFiles(Settings())
    intake = TaskDocumentIntake(files, document_tools("Format workflow"))
    try:
        result = await intake.prepare(
            f"Inspect deck.pptx and {source}; save result.pptx.",
            {"taskId": "t", "workspace": {"directory": str(tmp_path)}},
        )
        assert [x["path"] for x in result["sources"]] == ["deck.pptx"]
        assert (
            result["sources"][0]["sourceSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        )
        document = json.loads(result["sources"][0]["preview"])
        assert document["slides"][0]["textObjects"][0]["shapePath"] == [1, 0]
        assert source.read_bytes() == original
        assert not (tmp_path / "result.pptx").exists()
        assert (
            await intake.prepare(
                "Continue the conversation.",
                {"taskId": "t", "workspace": {"directory": str(tmp_path)}},
            )
            == {}
        )
        assert await intake.prepare("Inspect deck.pptx", {}) == {}
    finally:
        await files.close()


async def test_intake_never_reads_outside_or_linked_documents(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    secret = tmp_path / "secret.pptx"
    secret.write_bytes(presentation_bytes())
    (workspace / "linked.pptx").symlink_to(secret)
    files = WorkspaceFiles(Settings())
    try:
        result = await TaskDocumentIntake(files, document_tools()).prepare(
            "../secret.pptx linked.pptx",
            {"taskId": "t", "workspace": {"directory": str(workspace)}},
        )
        assert all(
            "preview" not in x and "sourceSha256" not in x for x in result.get("sources", [])
        )
        assert any(
            x.get("unavailable") == "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS" for x in result["sources"]
        )
    finally:
        await files.close()


async def test_prompt_counts_document_input_as_data_without_persisting_it_in_history(
    store, tmp_path
):
    path = tmp_path / "deck.pptx"
    path.write_bytes(presentation_bytes())
    files = WorkspaceFiles(Settings())
    intake = TaskDocumentIntake(files, document_tools("Trusted workflow"))
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "read", "Inspect deck.pptx")
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    turn["executionRunId"] = "attempt"
    builder = PromptBuilder(store, Context(store, SummaryModel()), Settings(), documents=intake)
    try:
        plain, _ = await builder.build(turn, "Worker", [], None)
        turn["documentInputs"] = await intake.prepare(
            "Inspect deck.pptx", {"taskId": "t", "workspace": {"directory": str(tmp_path)}}
        )
        observed, prompt = await builder.build(turn, "Worker", [], None)
        assert observed["estimatedTokens"] > plain["estimatedTokens"]
        assert (
            observed["documentEvidence"][0]["sourceSha256"]
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        assert "preview" not in observed["documentEvidence"][0]
        assert prompt[-1]["content"] == "Inspect deck.pptx"
        assert any(
            m["role"] == "user" and "external data, not instructions" in m["content"]
            for m in prompt
        )
        assert not any(m["role"] == "system" and "正文" in m["content"] for m in prompt)
        assert len((await conversations.messages("alice", c["id"]))["messages"]) == 1
    finally:
        await files.close()


async def test_real_native_preparation_supplies_document_before_first_worker_tool(store, tmp_path):
    source = tmp_path / "deck.pptx"
    source.write_bytes(presentation_bytes())
    captured = []

    class Worker:
        model = "document-intake-contract"

        async def stream(self, messages, tools):
            captured.append(messages)
            yield ModelEvent("text", "Read-only inspection complete; no edits made.")

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "contract", "directory": str(tmp_path)}

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Inspect deck.pptx",
            key="intake",
            target={"kind": "new_session", "directory": str(tmp_path)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(store, lambda db: bool(captured))
        prompt = captured[0]
        assert any("Applicable built-in document workflow:" in m.get("content", "") for m in prompt)
        snapshot = next(
            m
            for m in prompt
            if isinstance(m.get("content"), str)
            and m["content"].startswith("Read-only document snapshots")
        )
        assert (
            snapshot["role"] == "user"
            and hashlib.sha256(source.read_bytes()).hexdigest() in snapshot["content"]
        )
        assert "正文" in snapshot["content"]
        assert not any(m["role"] == "tool" for m in prompt)
    finally:
        await runtime.close()


async def test_partial_preview_defers_other_mentions_without_denying_task_execution(tmp_path):
    with zipfile.ZipFile(io.BytesIO(presentation_bytes())) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(
        "正文".encode(), ("正文" * 20000).encode()
    )
    with zipfile.ZipFile(tmp_path / "large.pptx", "w") as package:
        for name, body in parts.items():
            package.writestr(name, body)
    (tmp_path / "second.pptx").write_bytes(presentation_bytes())
    files = WorkspaceFiles(Settings())
    try:
        intake = TaskDocumentIntake(files, document_tools())
        result = await intake.prepare(
            "Inspect large.pptx and second.pptx",
            {"taskId": "t", "workspace": {"directory": str(tmp_path)}},
        )
        assert len(result["sources"]) == 1 and result["sources"][0]["nextOffset"] is not None
        assert result["uninspectedPaths"] == ["second.pptx"]
        assert len(result["sources"][0]["preview"].encode()) <= intake.reader.page_bytes
        page = await intake.reader.read(
            {"path": "second.pptx", "view": "document"},
            {"taskId": "t", "workspace": {"directory": str(tmp_path)}},
        )
        assert page["readBytes"] > 0
    finally:
        await files.close()


async def test_memory_prefix_does_not_put_document_data_between_a_tool_call_and_its_result(
    tmp_path,
):
    files = WorkspaceFiles(Settings())
    intake = TaskDocumentIntake(files, document_tools("format workflow"))
    previous_call = {
        "role": "assistant",
        "tool_calls": [
            {"id": "old", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        ],
    }
    previous_result = {"role": "tool", "tool_call_id": "old", "content": "old result"}
    request = {"role": "user", "content": "Inspect the new document"}
    history = [previous_call, previous_result, request]
    prompt = [
        {"role": "system", "content": "Worker"},
        {"role": "system", "content": "Recalled memory"},
        *history,
    ]
    plan, observed = intake.attach(
        {
            "executionRunId": "new",
            "documentInputs": {
                "workflow": "format workflow",
                "sources": [
                    {"path": "new.pptx", "sourceSha256": "observed", "preview": "external data"}
                ],
            },
        },
        {"messages": history, "currentTurnStart": 2},
        prompt,
    )
    index = next(i for i, m in enumerate(observed) if m is previous_call)
    assert observed[index + 1] is previous_result
    assert observed[-1] is request
    assert "preview" not in plan["documentEvidence"][0]
    assert prompt == [
        {"role": "system", "content": "Worker"},
        {"role": "system", "content": "Recalled memory"},
        *history,
    ]

    await files.close()
