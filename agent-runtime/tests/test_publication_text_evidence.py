import json

import pytest
from test_main_file_image_inputs import main_read as main_read_fixture

from roami_agent.dispatch.publication_text_review import PublicationTextReview
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_text_evidence import reviewed_text
from roami_agent.storage.transcript_repository import message

main_read = main_read_fixture


async def text_fixture(
    fixture, *, pages=((1, 2000),), body="Exact post.\n真实证据。\nThird line.\n"
):
    runtime, turn, _, read = fixture
    artifact = await runtime.artifacts.put(
        "local", body.encode(), name="post.md", mime_type="text/markdown"
    )
    for offset, limit in pages:
        await read("artifact://" + artifact["id"], extra={"offset": offset, "limit": limit})
    mid = await runtime.db.call(
        lambda db: message(
            db,
            turn["conversation_id"],
            turn["branch_id"],
            "assistant",
            {"text": "Inspect this exact body before the independent decision"},
            turn_id=turn["id"],
        ),
        write=True,
    )
    binding = {
        "owner": "local",
        "role": "main",
        "conversation": turn["conversation_id"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "assistantMessageId": mid,
    }
    return runtime, turn, binding, [{"id": artifact["id"], "sha256": artifact["sha256"]}]


@pytest.mark.parametrize("pages", [((1, 2000),), ((1, 1), (2, 2)), ((1, 2), (1, 1), (2, 2))])
async def test_current_main_complete_utf8_read_covers_exact_frozen_bytes(main_read, pages):
    runtime, _, binding, required = await text_fixture(main_read, pages=pages)
    proof = await PublicationTextReview(runtime.db, runtime.artifacts).inspect(binding, required)
    assert (
        proof[0]["artifactId"] == required[0]["id"] and proof[0]["sha256"] == required[0]["sha256"]
    )
    assert proof[0]["reads"] and all(
        item["toolCallId"] and item["resultMessageId"] for item in proof[0]["reads"]
    )


async def test_partial_body_is_not_reviewed_from_metadata_or_same_filename(main_read):
    runtime, _, binding, required = await text_fixture(main_read, pages=((1, 1),))
    with pytest.raises(DomainError, match="PUBLICATION_TEXT_NOT_REVIEWED"):
        await runtime.db.call(lambda db: reviewed_text(db, binding, required))


@pytest.mark.parametrize(
    "fault",
    [
        "worker",
        "owner",
        "task",
        "lease",
        "ended",
        "stop",
        "forget",
        "deleted",
        "receipt_failed",
        "receipt_deleted",
        "body_changed",
        "wrong_turn",
    ],
)
async def test_wrong_scope_or_unavailable_text_cannot_reuse_an_old_read(main_read, fault):
    runtime, turn, binding, required = await text_fixture(main_read)
    if fault in {"worker", "owner", "task", "lease"}:
        name, value = {
            "worker": ("role", "worker"),
            "owner": ("owner", "other"),
            "task": ("taskId", "author-task"),
            "lease": ("leaseEpoch", binding["leaseEpoch"] + 1),
        }[fault]
        binding[name] = value
    elif fault == "ended":
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (turn["id"],)),
            write=True,
        )
    elif fault == "stop":
        await runtime.chat.interrupt("local", turn["conversation_id"], "stop")
    elif fault == "deleted":
        await runtime.artifacts.delete("local", required[0]["id"])
    elif fault == "forget":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO memory_tombstones(owner_id,source_fingerprint,canonical_key,created_ms) VALUES('local',?,'forgotten-body',1)",
                (required[0]["sha256"],),
            ),
            write=True,
        )
    elif fault == "receipt_failed":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tool_calls SET state='failed' WHERE turn_id=?", (turn["id"],)
            ),
            write=True,
        )
    elif fault == "receipt_deleted":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE messages SET deleted_ms=1 WHERE role='tool' AND turn_id=?", (turn["id"],)
            ),
            write=True,
        )
    elif fault == "wrong_turn":
        other = await runtime.conversations.create("local")
        binding["conversation"] = other["id"]
    else:
        required[0]["sha256"] = "0" * 64
    with pytest.raises(DomainError):
        await PublicationTextReview(runtime.db, runtime.artifacts).inspect(binding, required)


async def test_stop_during_blob_integrity_check_cannot_finish_text_evidence(main_read, monkeypatch):
    runtime, turn, binding, required = await text_fixture(main_read)
    original = runtime.artifacts.verified_path

    async def interrupt(owner, artifact):
        result = await original(owner, artifact)
        await runtime.chat.interrupt("local", turn["conversation_id"], "stop-during-read-proof")
        return result

    monkeypatch.setattr(runtime.artifacts, "verified_path", interrupt)
    with pytest.raises(DomainError):
        await PublicationTextReview(runtime.db, runtime.artifacts).inspect(binding, required)


async def test_receipt_text_hash_cannot_be_replaced_while_retaining_frozen_metadata(main_read):
    runtime, turn, binding, required = await text_fixture(main_read)

    def corrupt(db):
        for receipt in db.execute(
            "SELECT id,content_json FROM messages WHERE role='tool' AND turn_id=?", (turn["id"],)
        ).fetchall():
            outer = json.loads(receipt["content_json"])
            value = json.loads(outer["text"])
            value["text"] = "Different content with unchanged reference"
            outer["text"] = json.dumps(value)
            db.execute(
                "UPDATE messages SET content_json=? WHERE id=?", (json.dumps(outer), receipt["id"])
            )

    await runtime.db.call(corrupt, write=True)
    with pytest.raises(DomainError, match="PUBLICATION_TEXT_NOT_REVIEWED"):
        await runtime.db.call(lambda db: reviewed_text(db, binding, required))
