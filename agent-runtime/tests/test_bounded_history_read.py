"""History evidence stays pageable, private and outside the live tool protocol."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.conversation.history_read import MAX_RESPONSE_BYTES, read_history
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.transcript_repository import message


class UnusedMain:
    model = "history-reader-fixture"


async def fixture(store, contents):
    runtime = Runtime(store, UnusedMain(), settings=Settings(workers=0))
    conversation = await runtime.conversations.create("alice")
    mids = await store.call(
        lambda db: [
            message(db, conversation["id"], conversation["active_branch_id"], role, content)
            for role, content in contents
        ],
        write=True,
    )
    receipt = await runtime.conversations.accept(
        "alice", conversation["id"], "read-history", "Read earlier evidence"
    )
    binding = {"owner": "alice", "conversation": conversation["id"], "turnId": receipt["turnId"]}
    return runtime, conversation, binding, mids


async def read(store, binding, args):
    return await store.call(lambda db: read_history(db, binding, args))


async def test_large_unicode_history_pages_preserve_every_id_and_strict_byte_budget(store):
    runtime, _, binding, mids = await fixture(
        store, [("assistant", {"text": f"record-{i}:" + "公开证据" * 3000}) for i in range(47)]
    )
    try:
        before, collected = None, []
        for _ in range(50):
            result = await read(
                store, binding, {"limit": 20, **({"before": before} if before else {})}
            )
            assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES
            assert result["historyView"] == "page"
            assert len(result["messages"]) < 20
            collected = [m["messageId"] for m in result["messages"]] + collected
            if not result["page"]["hasMore"]:
                break
            assert result["page"]["olderCursor"] not in {None, before}
            before = result["page"]["olderCursor"]
        else:
            pytest.fail("cursor did not progress")
        assert collected == mids
    finally:
        await runtime.close()


async def test_single_record_chunks_recover_exact_long_original_and_never_preview(store):
    original = "START " + '中文"\n' * 5000 + " EXACT_END"
    runtime, _, binding, mids = await fixture(
        store,
        [
            (
                "tool",
                {
                    "text": original,
                    "tool_call_id": "old-call",
                    "replyPreview": {"text": "PRIVATE_DRAFT"},
                },
            )
        ],
    )
    try:
        offset, chunks = 0, []
        for _ in range(100):
            result = await read(store, binding, {"messageId": mids[0], "offset": offset})
            record = result["messages"][0]
            chunks.append(record["content"])
            assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES
            if record["nextOffset"] is None:
                break
            assert record["nextOffset"] > offset
            offset = record["nextOffset"]
        else:
            pytest.fail("chunk did not progress")
        restored = json.loads("".join(chunks))
        assert restored == {"text": original, "tool_call_id": "old-call"}
        with pytest.raises(DomainError, match="INVALID_MESSAGE_OFFSET"):
            await read(store, binding, {"messageId": mids[0], "offset": len("".join(chunks)) + 1})
    finally:
        await runtime.close()


async def test_forgotten_sources_and_deleted_records_never_return_and_empty_pages_progress(store):
    runtime, conversation, binding, mids = await fixture(
        store,
        [
            ("assistant", {"text": "VISIBLE_OLDER"}),
            ("user", {"text": "FORGOTTEN_SOURCE"}),
            ("assistant", {"text": "DELETED_RECORD"}),
        ],
    )
    try:

        def seed(db):
            db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',0)",
                (mids[1],),
            )
            db.execute("UPDATE messages SET status='deleted',deleted_ms=1 WHERE id=?", (mids[2],))
            # Place these before the current turn's first message without changing their identity.
            current = db.execute(
                "SELECT seq FROM messages WHERE turn_id=?", (binding["turnId"],)
            ).fetchone()[0]
            db.execute("UPDATE messages SET seq=seq+100 WHERE turn_id=?", (binding["turnId"],))
            for i in range(15):
                mid = message(
                    db,
                    conversation["id"],
                    conversation["active_branch_id"],
                    "user",
                    {
                        "text": "FORGOTTEN_SOURCE_COPY",
                        "taskSteer": True,
                        "sourceUserMessageId": mids[1],
                    },
                )
                db.execute("UPDATE messages SET seq=? WHERE id=?", (current + i, mid))
            db.execute(
                "UPDATE branches SET head_seq=? WHERE id=?",
                (current + 100, conversation["active_branch_id"]),
            )
            return mid

        hidden = await store.call(seed, write=True)
        before, texts, saw_empty = None, [], False
        for _ in range(30):
            result = await read(
                store, binding, {"limit": 3, **({"before": before} if before else {})}
            )
            saw_empty |= not result["messages"] and result["page"]["hasMore"]
            texts += [m["content"] for m in result["messages"]]
            assert "FORGOTTEN" not in str(result) and "DELETED_RECORD" not in str(result)
            if not result["page"]["hasMore"]:
                break
            assert result["page"]["olderCursor"] not in {None, before}
            before = result["page"]["olderCursor"]
        else:
            pytest.fail("empty page stranded the cursor")
        assert saw_empty and len(texts) == 1 and "VISIBLE_OLDER" in texts[0]
        for mid in [mids[1], mids[2], hidden]:
            with pytest.raises(DomainError):
                await read(store, binding, {"messageId": mid})
    finally:
        await runtime.close()


async def test_actual_turn_branch_fork_cut_and_current_future_boundaries(store):
    runtime = Runtime(store, UnusedMain(), settings=Settings(workers=0))
    try:
        c = await runtime.conversations.create("alice")
        parent = c["active_branch_id"]
        a, b, after_cut = await store.call(
            lambda db: [
                message(db, c["id"], parent, "assistant", {"text": t})
                for t in ["A", "B", "AFTER_CUT"]
            ],
            write=True,
        )
        child = (await runtime.conversations.fork("alice", c["id"], b))["branchId"]
        own = await store.call(
            lambda db: message(db, c["id"], child, "assistant", {"text": "OWN"}), write=True
        )
        sibling = (await runtime.conversations.fork("alice", c["id"], b))["branchId"]
        foreign = await store.call(
            lambda db: message(db, c["id"], sibling, "assistant", {"text": "SIBLING"}), write=True
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET active_branch_id=? WHERE id=?", (child, c["id"])
            ),
            write=True,
        )
        receipt = await runtime.conversations.accept("alice", c["id"], "current", "CURRENT_INPUT")
        binding = {"owner": "alice", "conversation": c["id"], "turnId": receipt["turnId"]}

        def later(db):
            db.execute("UPDATE conversations SET active_branch_id=? WHERE id=?", (sibling, c["id"]))
            current = db.execute(
                "SELECT id FROM messages WHERE turn_id=?", (binding["turnId"],)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES('future',?,?,'user','queued',9999999999999)",
                (c["id"], child),
            )
            future = message(db, c["id"], child, "user", {"text": "FUTURE_INPUT"}, turn_id="future")
            return current, future

        current, future = await store.call(later, write=True)
        result = await read(store, binding, {})
        assert [m["messageId"] for m in result["messages"]] == [a, b, own]
        for mid in [after_cut, foreign, current, future]:
            for selector in ["messageId", "before"]:
                with pytest.raises(DomainError):
                    await read(store, binding, {selector: mid})
        other = await runtime.conversations.create("alice")
        for changed in [{"owner": "mallory"}, {"conversation": other["id"]}]:
            with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
                await read(store, {**binding, **changed}, {})
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "args",
    [
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"offset": 1},
        {"messageId": "a", "before": "b"},
        {"messageId": "a", "limit": 1},
        {"messageId": "a", "offset": -1},
        {"before": ""},
        {"messageId": ""},
        {"branchId": "foreign"},
    ],
)
async def test_invalid_selectors_cannot_expand_the_read(store, args):
    with pytest.raises(DomainError, match="INVALID_HISTORY_REQUEST"):
        await store.call(lambda db: read_history(db, {}, args))
