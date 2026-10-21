"""A delivered legacy prompt must have a durable, correctly routed return path."""

import asyncio
import json
import shlex

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.context.projection import model_messages
from roami_agent.conversation.session_dispatches import SessionDispatches
from roami_agent.executors import targets
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.storage.database import Database, row


async def origin(runtime, key="one"):
    c = await runtime.conversations.create("alice", title=key)
    accepted = await runtime.conversations.accept("alice", c["id"], key, "Commit and open a PR")
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (accepted["turnId"],))
    )
    message = await runtime.journal.origin(turn)
    return {
        "owner": "alice",
        "conversation": c["id"],
        "turnId": turn["id"],
        "originMessageId": message["id"],
        "toolCallId": key,
    }


async def prepare(runtime, binding, key="one"):
    return await runtime.session_dispatches.prepare("session-codex", "Open a PR", key, binding)


async def test_delivery_includes_stable_callback_and_never_replays_an_unknown_send(
    store, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    calls = []

    async def execute(argv, **kwargs):
        calls.append(json.loads(kwargs["input_data"]))
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {"session": "session-codex", "state": "delivered", "outcomeKnown": True}
            ),
        }

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(runtime.settings, runtime.session_dispatches)
    receipt = await directory.send("session-codex", "Open a PR", "one", binding=binding)
    assert receipt["replyExpected"] and not receipt["executionTracked"]
    assert "agent reply --dispatch " + receipt["dispatchId"] in calls[0]["text"]
    assert calls[0]["text"].startswith("Open a PR")
    assert receipt == await directory.send("session-codex", "Open a PR", "one", binding=binding)
    assert len(calls) == 1
    with pytest.raises(DomainError, match="MESSAGE_KEY_CONFLICT"):
        await directory.send("session-codex", "Different work", "one", binding=binding)

    async def unknown(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(targets, "execute", unknown)
    with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
        await directory.send("session-codex", "Second work", "two", binding=binding)
    monkeypatch.setattr(targets, "execute", execute)
    with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
        await directory.send("session-codex", "Second work", "two", binding=binding)
    assert len(calls) == 1


async def test_reports_return_only_to_original_branch_survive_service_recreation_and_dedupe(store):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    other = await origin(runtime, "other")
    dispatch = await prepare(runtime, binding)
    service = SessionDispatches(store, runtime.settings)
    result = {
        "key": "final",
        "status": "completed",
        "summary": "PR: https://example.com/pr/1; tests passed. Limit: local queue.",
    }
    first, second = await asyncio.gather(
        service.report("alice", dispatch["id"], result),
        service.report("alice", dispatch["id"], result),
    )
    assert first["messageId"] == second["messageId"] and first["verified"] is False
    assert {first["reused"], second["reused"]} == {True, False}
    view = await runtime.conversations.messages("alice", binding["conversation"])
    report = next(m for m in view["messages"] if m["id"] == first["messageId"])
    assert report["branch_id"] == dispatch["branch_id"]
    assert report["content"]["sessionReply"]["status"] == "completed"
    assert (await runtime.conversations.messages("alice", other["conversation"]))["messages"][-1][
        "role"
    ] == "user"
    projected = model_messages(
        [
            {
                "id": report["id"],
                "role": "assistant",
                "status": "completed",
                "turn_id": None,
                "content_json": json.dumps(report["content"]),
            }
        ]
    )
    assert (
        dispatch["id"] in projected[0]["content"]
        and "not independent verification" in projected[0]["content"]
    )
    assert await runtime.notifications.unread("alice") == 1
    assert (await service.status("alice", binding["conversation"], dispatch["id"]))[
        "replyStatus"
    ] == "completed"
    with pytest.raises(DomainError, match="SESSION_DISPATCH_NOT_FOUND"):
        await service.report("bob", dispatch["id"], result)
    with pytest.raises(DomainError, match="SESSION_REPORT_KEY_CONFLICT"):
        await service.report("alice", dispatch["id"], {**result, "summary": "Changed"})
    with pytest.raises(DomainError, match="SESSION_DISPATCH_ALREADY_REPORTED"):
        await service.report("alice", dispatch["id"], {**result, "key": "another-final"})


async def test_progress_and_choices_precede_final_failure_and_http_rejects_spoofed_routes(store):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    dispatch = await prepare(runtime, binding)
    app = create_app(runtime, manage_lifecycle=False)
    endpoint = f"/internal/session-dispatches/{dispatch['id']}/reply"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        result = {"key": "progress-1", "status": "progress", "summary": "Running checks"}
        assert (await client.post(endpoint, json=result)).status_code == 200
        assert (
            await client.post(endpoint, json={**result, "conversationId": "another-main"})
        ).status_code == 422
        assert (
            await client.post(endpoint, json={**result, "status": "unknown"})
        ).status_code == 422
        question = {"prompt": "Choose base", "options": [{"label": "main"}, {"label": "release"}]}
        blocker = {
            "key": "blocker",
            "status": "blocked",
            "summary": "Base branch decision needed",
            "question": question,
        }
        assert (await client.post(endpoint, json=blocker)).status_code == 200
        assert (
            await client.post(
                endpoint,
                json={
                    **blocker,
                    "question": {**question, "options": [{"label": "x"}, {"label": "x"}]},
                },
            )
        ).status_code == 422
        assert (
            await client.post(
                endpoint, json={"key": "final", "status": "failed", "summary": "Build failed"}
            )
        ).status_code == 200
        view = await runtime.conversations.messages("alice", binding["conversation"])
        reports = [m for m in view["messages"] if m["content"].get("sessionReply")]
        assert [m["content"]["sessionReply"]["status"] for m in reports] == [
            "progress",
            "blocked",
            "failed",
        ]
        assert len(reports[1]["content"]["question"]["options"]) == 2
        assert not any(m["content"]["sessionReply"]["verified"] for m in reports)
        events = await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM events WHERE conversation_id=? AND kind='message.completed'",
                (binding["conversation"],),
            ).fetchone()[0]
        )
        assert events == 3


async def test_forgotten_origin_cannot_return_to_context_or_leak_through_status(store):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    dispatch = await prepare(runtime, binding)
    await store.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,?,0)",
            ("alice", binding["originMessageId"], "test"),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.session_dispatches.report(
            "alice",
            dispatch["id"],
            {"key": "final", "status": "completed", "summary": "Forgotten content"},
        )
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.session_dispatches.status("alice", binding["conversation"], dispatch["id"])


async def test_callback_keeps_instance_paths_and_uses_shell_quoting_without_credentials(store):
    store.instance_paths = {
        key: "/tmp/instance 'quoted'/" + key
        for key in ["homeRoot", "dataRoot", "databaseRoot", "backupRoot"]
    }
    service = SessionDispatches(store, Settings(cli_bin="/tmp/roami path"))
    argv = shlex.split(service.reply_command("real-dispatch"))
    assert argv[0] == "env" and "ROAMI_HOME=" + store.instance_paths["homeRoot"] in argv
    assert argv[-7:] == [
        "/tmp/roami path",
        "agent",
        "reply",
        "--dispatch",
        "real-dispatch",
        "--file",
        "RESULT.json",
    ]
    assert not any("KEY=" in arg or "TOKEN=" in arg for arg in argv)


async def test_pending_callback_survives_database_reopen_and_missing_report_stays_unconfirmed(
    store,
):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    dispatch = await prepare(runtime, binding)
    await store.close()
    recovered = Database(store.path, store.data_root, managed=False)
    await recovered.open()
    try:
        service = SessionDispatches(recovered, runtime.settings)
        status = await service.status("alice", binding["conversation"], dispatch["id"])
        assert status["replyStatus"] == "unconfirmed" and status["verified"] is False
        result = {"key": "final", "status": "failed", "summary": "Actual executor failure"}
        receipt = await service.report("alice", dispatch["id"], result)
        assert not receipt["verified"] and receipt["status"] == "failed"
        assert (await service.report("alice", dispatch["id"], result))["reused"]
    finally:
        await recovered.close()


async def test_known_delivery_rejection_stays_failed_without_resending_or_accepting_a_result(
    store, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    binding = await origin(runtime)
    calls = []

    async def execute(*args, **kwargs):
        calls.append(True)
        return {"exitCode": 1, "stderr": "SESSION_TARGET_NOT_FOUND"}

    monkeypatch.setattr(targets, "execute", execute)
    directory = TargetDirectory(runtime.settings, runtime.session_dispatches)
    for _ in range(2):
        with pytest.raises(DomainError, match="SESSION_TARGET_NOT_FOUND"):
            await directory.send("gone-session", "Work", "one", binding=binding)
    assert len(calls) == 1
    item = await store.call(lambda db: row(db, "SELECT * FROM session_dispatches"))
    status = await runtime.session_dispatches.status("alice", binding["conversation"], item["id"])
    assert status["delivery"] == "failed" and status["deliveryError"] == "SESSION_TARGET_NOT_FOUND"
    with pytest.raises(DomainError, match="SESSION_DISPATCH_NOT_DELIVERED"):
        await runtime.session_dispatches.report(
            "alice",
            item["id"],
            {"key": "final", "status": "completed", "summary": "Cannot be true"},
        )


async def test_schema_seven_upgrades_without_rewriting_main_history(tmp_path, monkeypatch):
    from roami_agent.storage import migrations

    path = tmp_path / "database/agents/runtime.db"
    with monkeypatch.context() as context:
        context.setattr(migrations, "SCHEMA_VERSION", 7)
        database = Database(path, tmp_path, managed=False)
        await database.open()
        runtime = Runtime(database, ConversationModel())
        binding = await origin(runtime)
        original = (await runtime.conversations.messages("alice", binding["conversation"]))[
            "messages"
        ]
        await database.close()
    database = Database(path, tmp_path, managed=False)
    await database.open()
    try:
        runtime = Runtime(database, ConversationModel())
        current = (await runtime.conversations.messages("alice", binding["conversation"]))[
            "messages"
        ]
        assert current == original
        assert (
            await database.call(
                lambda db: db.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
            )
            == migrations.SCHEMA_VERSION
        )
        assert (await prepare(runtime, binding))["origin_message_id"] == binding["originMessageId"]
    finally:
        await database.close()
