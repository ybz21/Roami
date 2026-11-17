"""Search candidates never bypass source, lineage, time or response boundaries."""

import json

import pytest
from test_bounded_history_read import fixture, read

from roami_agent.conversation.history_read import MAX_RESPONSE_BYTES
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.retrieval.conversation_search import index_pending
from roami_agent.storage.transcript_repository import message


async def drain_index(store):
    while await store.call(index_pending, write=True):
        pass


async def test_long_original_search_indexes_tail_and_reports_pending_coverage(store):
    runtime, _, binding, mids = await fixture(
        store,
        [
            ("user", {"text": "ordinary " * 20_000 + "保留源链接 BURIED_REFERENCE end"}),
            ("assistant", {"text": "newer unrelated content"}),
        ],
    )
    try:
        waiting = await read(store, binding, {"query": "BURIED_REFERENCE"})
        assert waiting["messages"] == [] and waiting["coverage"]["complete"] is False
        await drain_index(store)
        result = await read(store, binding, {"query": "BURIED_REFERENCE"})
        hit = result["messages"][0]
        assert hit["messageId"] == mids[0] and hit["offset"] > 32_000
        assert "BURIED_REFERENCE" in hit["content"] and result["coverage"]["complete"]
        assert len(encoded(result).encode()) <= MAX_RESPONSE_BYTES
        chinese = await read(store, binding, {"query": "保留源链接"})
        assert chinese["messages"][0]["messageId"] == mids[0]
        exact = await read(store, binding, {"messageId": mids[0], "offset": hit["offset"]})
        assert exact["messages"][0]["content"] == hit["content"]
    finally:
        await runtime.close()


async def test_search_edits_forgetting_deletion_and_other_owners_are_checked_live(store):
    runtime, conversation, binding, mids = await fixture(
        store,
        [
            ("user", {"text": "original_keyword"}),
            ("assistant", {"text": "forgotten_keyword"}),
        ],
    )
    try:
        other = await runtime.conversations.create("mallory")
        await store.call(
            lambda db: message(
                db,
                other["id"],
                other["active_branch_id"],
                "user",
                {"text": "original_keyword private_other_owner"},
            ),
            write=True,
        )
        await drain_index(store)
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (encoded({"text": "edited_keyword"}), mids[0]),
            ),
            write=True,
        )
        stale = await read(store, binding, {"query": "original_keyword"})
        assert not stale["messages"] and not stale["coverage"]["complete"]
        await drain_index(store)
        assert (await read(store, binding, {"query": "edited_keyword"}))["messages"][0][
            "messageId"
        ] == mids[0]
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',0)",
                (mids[1],),
            ),
            write=True,
        )
        assert not (await read(store, binding, {"query": "forgotten_keyword"}))["messages"]
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET status='deleted',deleted_ms=1 WHERE id=?", (mids[0],)
            ),
            write=True,
        )
        assert not (await read(store, binding, {"query": "edited_keyword"}))["messages"]
        assert not (await read(store, binding, {"query": "private_other_owner"}))["messages"]
        with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
            await read(store, {**binding, "owner": "mallory"}, {"query": "keyword"})
        assert conversation["id"] == binding["conversation"]
    finally:
        await runtime.close()


async def test_filtered_pages_preserve_dates_and_cursor_progress(store):
    runtime, _, binding, mids = await fixture(
        store, [("assistant", {"text": f"archive_keyword record_{i}"}) for i in range(25)]
    )
    try:
        await store.call(
            lambda db: [
                db.execute("UPDATE messages SET created_ms=? WHERE id=?", (1000 + index, mid))
                for index, mid in enumerate(mids)
            ],
            write=True,
        )
        await drain_index(store)
        before, found = None, []
        for _ in range(20):
            result = await read(
                store,
                binding,
                {
                    "query": "archive_keyword",
                    "sinceMs": 1005,
                    "untilMs": 1020,
                    "limit": 3,
                    **({"before": before} if before else {}),
                },
            )
            found = [m["messageId"] for m in result["messages"]] + found
            assert all(1005 <= m["createdMs"] < 1020 for m in result["messages"])
            if not result["page"]["hasMore"]:
                break
            assert result["page"]["olderCursor"] not in {before, None}
            before = result["page"]["olderCursor"]
        assert found == mids[5:20]
        dated = await read(store, binding, {"sinceMs": 1005, "untilMs": 1006})
        assert dated["messages"][0]["messageId"] == mids[5]
        assert json.loads(dated["messages"][0]["content"])["text"].endswith("record_5")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "args",
    [
        {"query": []},
        {"query": "***"},
        {"sinceMs": True},
        {"untilMs": -1},
        {"sinceMs": 100, "untilMs": 100},
        {"query": "a", "offset": 0},
        {"query": "a", "messageId": "x"},
        {"archiveDay": "2026-02-30"},
        {"archiveDay": "2026-11-12", "query": "x"},
    ],
)
async def test_invalid_search_does_not_change_reader_contract(store, args):
    runtime, _, binding, _ = await fixture(store, [])
    try:
        with pytest.raises(DomainError):
            await read(store, binding, args)
    finally:
        await runtime.close()


async def test_search_obeys_the_turn_branch_fork_cut_and_future_turn_boundary(store):
    runtime, c, _, mids = await fixture(
        store,
        [
            ("assistant", {"text": text})
            for text in ["needle_parent", "needle_cut", "needle_after_cut"]
        ],
    )
    try:
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET state='completed' WHERE conversation_id=?", (c["id"],)
            ),
            write=True,
        )
        child = (await runtime.conversations.fork("alice", c["id"], mids[1]))["branchId"]
        own = await store.call(
            lambda db: message(db, c["id"], child, "assistant", {"text": "needle_child"}),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET active_branch_id=? WHERE id=?",
                (c["active_branch_id"], c["id"]),
            ),
            write=True,
        )
        sibling = (await runtime.conversations.fork("alice", c["id"], mids[1]))["branchId"]
        await store.call(
            lambda db: message(db, c["id"], sibling, "assistant", {"text": "needle_sibling"}),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET active_branch_id=? WHERE id=?", (child, c["id"])
            ),
            write=True,
        )
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "fork-search", "needle_current"
        )
        await runtime.conversations.accept("alice", c["id"], "fork-future", "needle_future")
        await drain_index(store)
        binding = {"owner": "alice", "conversation": c["id"], "turnId": receipt["turnId"]}
        result = await read(store, binding, {"query": "needle_parent"})
        assert [value["messageId"] for value in result["messages"]] == [mids[0]]
        for query in ["needle_after_cut", "needle_sibling", "needle_current", "needle_future"]:
            assert not (await read(store, binding, {"query": query}))["messages"]
        assert (await read(store, binding, {"query": "needle_child"}))["messages"][0][
            "messageId"
        ] == own
    finally:
        await runtime.close()


async def test_stable_failed_and_interrupted_originals_remain_readable_and_searchable(store):
    runtime, _c, binding, mids = await fixture(
        store,
        [
            ("assistant", {"text": "interrupted_reference partial output"}),
            ("tool", {"text": "failed_reference unknown outcome", "tool_call_id": "old-call"}),
        ],
    )
    try:
        for mid, status in zip(mids, ["interrupted", "failed"], strict=True):
            await store.call(
                lambda db, mid=mid, status=status: db.execute(
                    "UPDATE messages SET status=? WHERE id=?", (status, mid)
                ),
                write=True,
            )
            exact = await read(store, binding, {"messageId": mid})
            assert exact["messages"][0]["status"] == status
        await drain_index(store)
        for mid, query, status in zip(
            mids,
            ["interrupted_reference", "failed_reference"],
            ["interrupted", "failed"],
            strict=True,
        ):
            result = await read(store, binding, {"query": query})
            assert result["messages"][0]["messageId"] == mid
            assert result["messages"][0]["status"] == status
    finally:
        await runtime.close()
