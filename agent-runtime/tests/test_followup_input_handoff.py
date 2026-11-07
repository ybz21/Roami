"""Admitted images stay with the same task/session across follow-ups and retries."""

import hashlib
import io
import json

import pytest
from PIL import Image
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.professional_brief import professional_brief
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


async def user_turn(runtime, conversation, key, text, files=()):
    def settle_previous(db):
        db.execute(
            "UPDATE turns SET state='completed' WHERE conversation_id=? AND state IN ('queued','running')",
            (conversation["id"],),
        )
        db.execute(
            "UPDATE jobs SET state='done' WHERE kind='turn.run' AND aggregate_id IN (SELECT id FROM turns WHERE conversation_id=?)",
            (conversation["id"],),
        )

    await runtime.db.call(settle_previous, write=True)
    source = await runtime.conversations.accept(
        "alice", conversation["id"], key, text, [f["id"] for f in files]
    )
    job = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (source["turnId"],))
    )
    await runtime.mailbox.claim(job)
    return {
        "owner": "alice",
        "conversation": conversation["id"],
        "turnId": source["turnId"],
        "originMessageId": source["messageId"],
        "toolCallId": key,
    }


async def screenshot(runtime, key):
    output = io.BytesIO()
    Image.new("RGB", (32, 24), tuple(hashlib.sha256(key.encode()).digest()[:3])).save(
        output, format="PNG"
    )
    return await runtime.attachments.upload("alice", key + ".png", key, output.getvalue())


async def finish(runtime, task):
    def write(db):
        db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='succeeded',session_id=CASE WHEN executor_kind='cli' THEN 'original-session' END,result_json=? "
            "WHERE task_id=? AND task_revision=(SELECT revision FROM tasks WHERE id=?)",
            (json.dumps({"state": "succeeded", "inputStopped": True}), task["id"], task["id"]),
        )

    await runtime.db.call(write, write=True)


async def brief(runtime, task_id):
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task_id,)),
        write=True,
    )
    task = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
    run = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC", (task_id,)
        )
    )
    return await professional_brief(runtime.db, runtime.artifacts, task, run, continuation=True)


async def test_existing_session_receives_current_image_and_file_once(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        unused = await screenshot(runtime, "unrelated")
        await user_turn(runtime, c, "other", "Other request", [unused])
        image = await screenshot(runtime, "diagram")
        notes = await runtime.attachments.upload("alice", "notes.md", "notes", b"Diagram notes")
        binding = await user_turn(
            runtime, c, "send", "Fix this diagram in the original session", [image, notes]
        )
        sent = []

        async def execute(argv, **kwargs):
            if argv[1:3] == ["session", "resolve"]:
                return {
                    "exitCode": 0,
                    "stdout": json.dumps({"id": "original-session", "label": "X"}),
                }
            sent.append(json.loads(kwargs["input_data"]))
            return {
                "exitCode": 0,
                "stdout": json.dumps(
                    {"session": "original-session", "state": "delivered", "outcomeKnown": True}
                ),
            }

        monkeypatch.setattr("roami_agent.executors.targets.execute", execute)
        target = TargetDirectory(runtime.settings, runtime.session_dispatches)
        receipt = await target.send("original-session", "Fix this diagram", "send", binding=binding)
        assert (
            await target.send("original-session", "Fix this diagram", "send", binding=binding)
            == receipt
        )
        assert len(sent) == 1 and sent[0]["sessionId"] == "original-session"
        prompt = sent[0]["text"]
        assert "untrusted" in prompt and "image/png" in prompt and "notes.md" in prompt
        assert image["id"] in prompt and notes["sha256"] in prompt
        assert unused["id"] not in prompt
        _, path = await runtime.artifacts.verified_path("alice", image["id"])
        assert str(path) in prompt
    finally:
        await runtime.close()


@pytest.mark.parametrize("fault", ["tamper", "missing", "deleted", "forgotten"])
async def test_unavailable_session_input_rejects_before_dispatch(store, monkeypatch, fault):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        image = await screenshot(runtime, "diagram")
        binding = await user_turn(runtime, c, "send", "Fix this image", [image])
        _, path = await runtime.artifacts.verified_path("alice", image["id"])
        if fault == "tamper":
            path.chmod(0o600)
            path.write_bytes(b"changed")
        elif fault == "missing":
            path.unlink()
        elif fault == "deleted":
            await store.call(
                lambda db: db.execute(
                    "UPDATE artifacts SET deleted_ms=1 WHERE id=?", (image["id"],)
                ),
                write=True,
            )
        else:
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (binding["originMessageId"],),
                ),
                write=True,
            )
        sent = []

        async def execute(*args, **kwargs):
            sent.append(True)
            return {
                "exitCode": 0,
                "stdout": json.dumps(
                    {"session": "original-session", "state": "delivered", "outcomeKnown": True}
                ),
            }

        monkeypatch.setattr("roami_agent.executors.targets.execute", execute)
        target = TargetDirectory(runtime.settings, runtime.session_dispatches)
        with pytest.raises(DomainError):
            await target.send("original-session", "Fix this image", "send", binding=binding)
        assert not sent
        assert not await store.call(lambda db: row(db, "SELECT id FROM session_dispatches"))
    finally:
        await runtime.close()


async def test_task_inputs_survive_multiple_text_followups_without_unrelated_images(store):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        initial = await screenshot(runtime, "initial")
        binding = await user_turn(runtime, c, "initial", "Draw this", [initial])
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Draw this",
            key="task",
            executor="codex",
            origin_message_id=binding["originMessageId"],
        )
        await finish(runtime, task)
        later = await screenshot(runtime, "later")
        source = await user_turn(runtime, c, "more", "Add this annotation", [later])
        await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Add annotation",
            1,
            "more",
            source_turn_id=source["turnId"],
            source_conversation_id=c["id"],
        )
        await runtime.tasks.revisions.advance()
        await finish(runtime, task)
        unused = await screenshot(runtime, "other")
        await user_turn(runtime, c, "other", "Unrelated image", [unused])
        source = await user_turn(runtime, c, "text", "Continue with the same images")
        await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Continue",
            2,
            "text",
            source_turn_id=source["turnId"],
            source_conversation_id=c["id"],
        )
        await runtime.tasks.revisions.advance()
        prompt = await brief(runtime, task["id"])
        assert initial["id"] in prompt and later["id"] in prompt
        assert prompt.count(initial["id"]) == prompt.count(later["id"]) == 1
        assert unused["id"] not in prompt
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        assert (
            current["revision"] == 3 and json.loads(current["intent_json"])["executor"] == "codex"
        )
        assert json.loads(current["intent_json"])["target"]["sessionId"] == "original-session"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "legacy,forgotten", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_continuation_inputs_follow_real_source_not_audit_copy(store, legacy, forgotten):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        await user_turn(runtime, c, "initial", "Original work")
        task = await runtime.tasks.create(
            "alice", c["id"], "Original work", key="task", executor="codex"
        )
        await finish(runtime, task)
        image = await screenshot(runtime, "followup")
        source = await user_turn(runtime, c, "followup", "Fix this image", [image])
        op = await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Fix image",
            1,
            "followup",
            source_turn_id=source["turnId"],
            source_conversation_id=c["id"],
        )
        await runtime.tasks.revisions.advance()
        current = (await runtime.tasks.get("alice", task["id"]))["task"]

        def strip(db):
            audit = row(db, "SELECT * FROM messages WHERE id=?", (current["origin_message_id"],))
            content = json.loads(audit["content_json"])
            content.pop("attachments", None)
            if legacy:
                content.pop("sourceUserMessageId", None)
                assistant = message(
                    db,
                    c["id"],
                    task["origin_branch_id"],
                    "assistant",
                    {"text": ""},
                    turn_id=source["turnId"],
                )
                result = message(
                    db,
                    c["id"],
                    task["origin_branch_id"],
                    "tool",
                    {"text": json.dumps(op)},
                    turn_id=source["turnId"],
                )
                db.execute(
                    "INSERT INTO tool_calls(id,turn_id,assistant_message_id,result_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) VALUES('legacy-steer',?,?,?,'task_steer','{}','write','succeeded','legacy-steer',1,1)",
                    (source["turnId"], assistant, result),
                )
            db.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (json.dumps(content), audit["id"]),
            )
            if forgotten:
                db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (source["originMessageId"],),
                )

        await store.call(strip, write=True)
        if forgotten:
            with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
                await brief(runtime, task["id"])
        else:
            assert image["id"] in await brief(runtime, task["id"])
    finally:
        await runtime.close()


async def test_session_input_forgotten_during_integrity_check_does_not_send(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        image = await screenshot(runtime, "diagram")
        binding = await user_turn(runtime, c, "send", "Use this diagram", [image])
        verify = runtime.artifacts.verified_path

        async def forget(owner, aid):
            result = await verify(owner, aid)
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (binding["originMessageId"],),
                ),
                write=True,
            )
            return result

        monkeypatch.setattr(runtime.artifacts, "verified_path", forget)

        async def resolve(kind, identifier):
            return {"sessionId": identifier}

        with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
            await runtime.session_dispatches.prepare(
                "original-session", "Use this diagram", "send", binding, resolve=resolve
            )
        assert not await store.call(lambda db: row(db, "SELECT id FROM session_dispatches"))
    finally:
        await runtime.close()


async def test_unknown_image_delivery_is_not_replayed(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        image = await screenshot(runtime, "diagram")
        binding = await user_turn(runtime, c, "send", "Use this diagram", [image])
        sent = []

        async def execute(argv, **kwargs):
            if argv[1:3] == ["session", "resolve"]:
                return {
                    "exitCode": 0,
                    "stdout": json.dumps({"id": "original-session", "label": "X"}),
                }
            sent.append(json.loads(kwargs["input_data"]))
            raise TimeoutError

        monkeypatch.setattr("roami_agent.executors.targets.execute", execute)
        target = TargetDirectory(runtime.settings, runtime.session_dispatches)
        for _ in range(2):
            with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
                await target.send("original-session", "Use this diagram", "send", binding=binding)
        assert len(sent) == 1 and image["id"] in sent[0]["text"]
        dispatch = await store.call(lambda db: row(db, "SELECT * FROM session_dispatches"))
        assert dispatch["delivery_state"] == "unknown" and not dispatch["final_status"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("revoked", [None, "source", "attachment"])
async def test_native_followup_uses_actual_source_after_legacy_snapshot_loss(store, revoked):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        await user_turn(runtime, c, "initial", "Original work")
        task = await runtime.tasks.create("alice", c["id"], "Original work", key="task")
        await finish(runtime, task)
        image = await screenshot(runtime, "diagram")
        source = await user_turn(runtime, c, "followup", "Update this diagram", [image])
        op = await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Update diagram",
            1,
            "followup",
            source_turn_id=source["turnId"],
            source_conversation_id=c["id"],
        )

        def legacy_snapshot(db):
            job = row(db, "SELECT * FROM jobs WHERE id=?", (op["operationId"],))
            payload = json.loads(job["payload_json"])
            payload["attachments"] = []
            db.execute(
                "UPDATE jobs SET payload_json=? WHERE id=?", (json.dumps(payload), job["id"])
            )
            audit = row(db, "SELECT * FROM messages WHERE id=?", (payload["messageId"],))
            content = json.loads(audit["content_json"])
            content.pop("attachments", None)
            db.execute(
                "UPDATE messages SET content_json=? WHERE id=?", (json.dumps(content), audit["id"])
            )
            if revoked == "source":
                db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',1)",
                    (source["originMessageId"],),
                )
            elif revoked == "attachment":
                db.execute("UPDATE artifacts SET deleted_ms=1 WHERE id=?", (image["id"],))

        await store.call(legacy_snapshot, write=True)
        await runtime.tasks.revisions.advance()
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        operation = await runtime.tasks.revisions.get("alice", task["id"], op["operationId"])
        if revoked:
            assert current["revision"] == 1
            assert operation["state"] == "blocked"
            assert operation["errorCode"] == (
                "TASK_SOURCE_FORGOTTEN" if revoked == "source" else "ATTACHMENT_NOT_FOUND"
            )
        else:
            assert current["revision"] == 2
            child = await store.call(
                lambda db: row(
                    db,
                    "SELECT m.content_json FROM messages m JOIN task_attempts a ON a.native_branch_id=m.branch_id WHERE a.task_id=? AND a.task_revision=2 ORDER BY m.seq DESC LIMIT 1",
                    (task["id"],),
                )
            )
            assert json.loads(child["content_json"])["attachments"][0]["id"] == image["id"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("outcome", ["delivered", "unknown"])
async def test_recorded_image_delivery_keeps_its_receipt_after_blob_removal(
    store, monkeypatch, outcome
):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        image = await screenshot(runtime, "diagram")
        binding = await user_turn(runtime, c, "send", "Update diagram", [image])
        _, path = await runtime.artifacts.verified_path("alice", image["id"])
        sent = []

        async def execute(argv, **kwargs):
            if argv[1:3] == ["session", "resolve"]:
                return {
                    "exitCode": 0,
                    "stdout": json.dumps({"id": "original-session", "label": "X"}),
                }
            sent.append(True)
            if outcome == "unknown":
                raise TimeoutError
            return {
                "exitCode": 0,
                "stdout": json.dumps(
                    {"session": "original-session", "state": "delivered", "outcomeKnown": True}
                ),
            }

        monkeypatch.setattr("roami_agent.executors.targets.execute", execute)
        target = TargetDirectory(runtime.settings, runtime.session_dispatches)
        if outcome == "unknown":
            with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
                await target.send("original-session", "Update diagram", "send", binding=binding)
        else:
            receipt = await target.send(
                "original-session", "Update diagram", "send", binding=binding
            )
        path.unlink()
        if outcome == "unknown":
            with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
                await target.send("original-session", "Update diagram", "send", binding=binding)
        else:
            assert (
                await target.send("original-session", "Update diagram", "send", binding=binding)
                == receipt
            )
        assert len(sent) == 1
    finally:
        await runtime.close()
