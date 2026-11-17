"""Idle/day handoff is atomic, source-verified and independent of model capacity."""

import asyncio
import json
from datetime import datetime

import pytest
from test_conversation_search import drain_index

from roami_agent.app import Runtime
from roami_agent.context.maintenance import daily_cutoff
from roami_agent.context.projection import context_history
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.context.working_brief import validate_candidate
from roami_agent.conversation.history_read import read_history
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import message


class BriefModel:
    model = "saved-route-fixture"

    def __init__(self):
        self.calls = []
        self.gate = None
        self.started = asyncio.Event()
        self.error = None

    async def stream(self, messages, tools):
        assert not tools
        self.calls.append(messages)
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        data = json.loads(messages[-1]["content"])
        users = [m for m in data["sources"] if m["role"] == "user"]
        candidate = {
            "reviewedUserIds": [m["id"] for m in users],
            "items": [],
            "superseded": [],
            "archives": {
                day: "Historical topics and outcomes; source batch only." for day in data["days"]
            },
        }
        for source in users:
            if "Do not deploy" in source["text"]:
                candidate["items"].append(
                    {"kind": "constraint", "text": "Do not deploy", "sourceIds": [source["id"]]}
                )
        yield ModelEvent("text", encoded(candidate))


async def home_fixture(store, count=26):
    model = BriefModel()
    runtime = Runtime(store, model, settings=Settings(workers=0, memory_timezone="Asia/Shanghai"))
    c = await runtime.conversations.create("alice")
    await store.call(
        lambda db: db.execute(
            "INSERT INTO main_conversations VALUES(?,?,?)", ("alice", c["id"], now_ms())
        ),
        write=True,
    )
    ids = []
    for index in range(count):
        receipt = await runtime.conversations.accept(
            "alice",
            c["id"],
            f"old-{index}",
            "Do not deploy" if index == 0 else f"One-off: list three facts item_{index}",
        )
        timestamp = now_ms() - (4 if index < count - 2 else 0) * 86_400_000

        def finish(db, receipt=receipt, timestamp=timestamp, index=index):
            mid = message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {
                    "text": "execution log " * 30 + f"result_{index}",
                    "replyPreview": {"text": "draft"},
                },
                turn_id=receipt["turnId"],
            )
            db.execute(
                "UPDATE turns SET state='completed',created_ms=?,finished_ms=? WHERE id=?",
                (timestamp, timestamp, receipt["turnId"]),
            )
            db.execute(
                "UPDATE messages SET created_ms=? WHERE turn_id=?", (timestamp, receipt["turnId"])
            )
            return mid

        ids.append((receipt["messageId"], await store.call(finish, write=True)))
    return runtime, c, model, ids


async def queued(store):
    return await store.call(
        lambda db: rows(
            db, "SELECT * FROM jobs WHERE kind='context.maintain' AND state='queued' ORDER BY rowid"
        )
    )


async def maintain_all(runtime):
    await drain_index(runtime.db)
    await runtime.context.maintenance.scan(force=True)
    for _ in range(20):
        jobs = await queued(runtime.db)
        if not jobs:
            return
        for job in jobs:
            await runtime.context.maintenance.run(job["id"])
    pytest.fail("maintenance cursor did not finish")


async def test_idle_handoff_shrinks_context_preserves_constraints_and_keeps_exact_sources(store):
    runtime, c, model, ids = await home_fixture(store)
    try:
        configuration = {"instructions": "test", "catalog": [], "contextMaintenance": True}
        original = await runtime.context.project("alice", c["id"], request_context=configuration)
        await maintain_all(runtime)
        assert len(model.calls) == 2
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "current", "A new unrelated question"
        )
        plan = await runtime.context.project(
            "alice", c["id"], through_turn=receipt["turnId"], request_context=configuration
        )
        assert plan["workingBriefId"] and plan["snapshotId"] is None
        assert plan["estimatedTokens"] < original["estimatedTokens"]
        assert "Do not deploy" in str(plan["messages"])
        assert 'item_1"' not in str(plan["messages"]) and 'result_1"' not in str(plan["messages"])
        assert plan["messages"][-1]["content"] == "A new unrelated question"
        binding = {"owner": "alice", "conversation": c["id"], "turnId": receipt["turnId"]}
        exact = await store.call(lambda db: read_history(db, binding, {"query": "item_1"}))
        assert exact["messages"][0]["messageId"] == ids[1][0]
        day = (
            await store.call(
                lambda db: row(
                    db, "SELECT day_key FROM period_summaries ORDER BY created_ms LIMIT 1"
                )
            )
        )["day_key"]
        archived = await store.call(lambda db: read_history(db, binding, {"archiveDay": day}))
        assert archived["parts"] and archived["parts"][0]["timezone"] == "Asia/Shanghai"
        assert archived["parts"][0]["coverage"] == "source_batch"
        count = len(model.calls)
        await runtime.context.maintenance.scan(force=True)
        for job in await queued(store):
            await runtime.context.maintenance.run(job["id"])
        assert len(model.calls) == count
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM messages WHERE branch_id=?", (c["active_branch_id"],)
                ).fetchone()[0]
            )
            == 53
        )
    finally:
        await runtime.close()


async def test_unindexed_sources_cannot_activate_or_remove_history(store):
    runtime, _c, model, _ = await home_fixture(store)
    try:
        await runtime.context.maintenance.scan(force=True)
        job = (await queued(store))[0]
        await runtime.context.maintenance.run(job["id"])
        assert not model.calls
        assert not await store.call(lambda db: row(db, "SELECT id FROM context_briefs"))
        await maintain_all(runtime)
        assert model.calls
    finally:
        await runtime.close()


@pytest.mark.parametrize("change", ["edit", "forget", "branch"])
async def test_inflight_stale_summary_cannot_activate_even_when_original_sources_are_appended(
    store, change
):
    runtime, c, model, ids = await home_fixture(store, count=5)
    model.gate = asyncio.Event()
    try:
        await drain_index(store)
        await runtime.context.maintenance.scan(force=True)
        job = (await queued(store))[0]
        running = asyncio.create_task(runtime.context.maintenance.run(job["id"]))
        await model.started.wait()
        if change == "edit":
            await store.call(
                lambda db: db.execute(
                    "UPDATE messages SET content_json=? WHERE id=?",
                    (encoded({"text": "changed source"}), ids[0][0]),
                ),
                write=True,
            )
        elif change == "forget":
            await store.call(
                lambda db: db.execute(
                    "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id='alice'"
                ),
                write=True,
            )
        else:
            await runtime.conversations.fork("alice", c["id"], ids[0][1])
        model.gate.set()
        await running
        assert not await store.call(lambda db: row(db, "SELECT id FROM context_briefs"))
        assert not await store.call(lambda db: row(db, "SELECT id FROM period_summaries"))
        failed = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],)))
        assert failed["state"] == "queued" and failed["available_ms"] > now_ms()
    finally:
        model.gate.set()
        await runtime.close()


async def test_failure_preserves_last_good_brief_and_recovery_requeues_lease(store):
    runtime, c, model, _ = await home_fixture(store, count=5)
    try:
        await maintain_all(runtime)
        previous = await store.call(
            lambda db: row(db, "SELECT * FROM context_briefs ORDER BY rowid DESC LIMIT 1")
        )
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "new-work", "Additional unfinished requirement"
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET state='completed',finished_ms=? WHERE id=?",
                (now_ms() - 700_000, receipt["turnId"]),
            ),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms() - 700_000, c["id"])
            ),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET finished_ms=? WHERE branch_id=?",
                (now_ms() - 700_000, c["active_branch_id"]),
            ),
            write=True,
        )
        await drain_index(store)
        await runtime.context.maintenance.scan(force=True)
        model.error = DomainError("MODEL_QUOTA_REJECTED", 429)
        job = (await queued(store))[0]
        await runtime.context.maintenance.run(job["id"])
        current = await store.call(
            lambda db: row(db, "SELECT * FROM context_briefs ORDER BY rowid DESC LIMIT 1")
        )
        assert current["id"] == previous["id"]
        retry = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],)))
        assert retry["state"] == "queued" and retry["available_ms"] > now_ms()
        await store.call(
            lambda db: db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],)),
            write=True,
        )
        await runtime.context.maintenance.recover()
        assert (await queued(store))[0]["id"] == job["id"]
    finally:
        await runtime.close()


def test_daily_cutoff_respects_dst_local_boundary_and_scheduled_time():
    def stamp(value):
        return int(datetime.fromisoformat(value).timestamp() * 1000)

    assert (
        daily_cutoff(stamp("2026-11-02T03:00:00-05:00"), "America/New_York")
        - daily_cutoff(stamp("2026-11-01T03:00:00-05:00"), "America/New_York")
        == 25 * 3_600_000
    )
    assert daily_cutoff(stamp("2026-11-17T02:09:00+08:00"), "Asia/Shanghai") == stamp(
        "2026-11-16T00:00:00+08:00"
    )
    assert daily_cutoff(stamp("2026-11-17T02:10:00+08:00"), "Asia/Shanghai") == stamp(
        "2026-11-17T00:00:00+08:00"
    )


async def test_brief_rejects_missing_coverage_and_assistant_constraints(store):
    runtime, c, _, _ = await home_fixture(store, count=3)
    try:
        source = await store.call(lambda db: context_history(db, c["active_branch_id"]))
        users = [m["id"] for m in source if m["role"] == "user"]
        candidate = {
            "reviewedUserIds": users,
            "items": [],
            "superseded": [],
            "archives": {"day": "archive"},
        }
        candidate["items"] = [
            {"kind": "constraint", "text": "invented restriction", "sourceIds": [users[0]]}
        ]
        with pytest.raises(DomainError, match="WORKING_BRIEF_QUOTE_MISMATCH"):
            validate_candidate(candidate, [], source, source, {"day"})
        candidate["items"] = []
        candidate["reviewedUserIds"] = []
        with pytest.raises(DomainError, match="WORKING_BRIEF_COVERAGE_MISSING"):
            validate_candidate(candidate, [], source, source, {"day"})
    finally:
        await runtime.close()


@pytest.mark.parametrize("capacity_fallback", [False, True])
async def test_all_unfinished_task_constraints_survive_even_beyond_recent_three(
    store, capacity_fallback
):
    runtime, c, model, ids = await home_fixture(store, count=8)
    try:
        await maintain_all(runtime)
        tasks = []
        for index in range(5):
            tasks.append(
                await runtime.tasks.create(
                    "alice",
                    c["id"],
                    f"Task {index}",
                    key=f"live-{index}",
                    origin_message_id=ids[index][0],
                )
            )
        if capacity_fallback:
            from test_context_provider import SummaryModel

            runtime.context.model = SummaryModel()
            job = await runtime.context.request(
                "alice", c["id"], "capacity-live", target_tokens=100
            )
            await runtime.context.run(job["id"])
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "continue-live", "Continue the oldest unfinished task"
        )
        turn = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],))
        )
        turn["owner_id"] = "alice"
        plan, prompt = await PromptBuilder(store, runtime.context, runtime.settings).build(
            turn, "test", [], None
        )
        assert {item["taskId"] for item in plan["workingTaskEvidence"]} == {
            task["id"] for task in tasks
        }
        assert all(task["id"] in str(prompt) for task in tasks)
        await runtime.manifests.record(turn, 1, model.model, "test-wire-hash", plan, [], "main")
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET revision=revision+1 WHERE id=?", (tasks[0]["id"],)
            ),
            write=True,
        )
        with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
            await store.call(lambda db: assert_context_admitted(db, turn))
    finally:
        await runtime.close()


async def test_archive_source_edit_invalidates_part_before_any_rebuild(store):
    runtime, c, _, ids = await home_fixture(store, count=5)
    try:
        await maintain_all(runtime)
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "read-days", "Read older days"
        )
        binding = {"owner": "alice", "conversation": c["id"], "turnId": receipt["turnId"]}
        day = (
            await store.call(lambda db: row(db, "SELECT day_key FROM period_summaries LIMIT 1"))
        )["day_key"]
        before = await store.call(lambda db: read_history(db, binding, {"archiveDay": day}))
        assert any(ids[0][0] in part["sourceMessageIds"] for part in before["parts"])
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (encoded({"text": "edited now"}), ids[0][0]),
            ),
            write=True,
        )
        after = await store.call(lambda db: read_history(db, binding, {"archiveDay": day}))
        assert all(ids[0][0] not in part["sourceMessageIds"] for part in after["parts"])
        plan = await runtime.context.project(
            "alice",
            c["id"],
            through_turn=receipt["turnId"],
            request_context={"instructions": "test", "catalog": [], "contextMaintenance": True},
        )
        assert plan["workingBriefId"] is None
        assert "edited now" in str(plan["messages"])
    finally:
        await runtime.close()


async def test_one_shared_chinese_character_does_not_recall_expired_format_requests(store):
    runtime, c, _, ids = await home_fixture(store, count=5)
    try:
        await maintain_all(runtime)

        def add_reference(db):
            brief = row(db, "SELECT * FROM context_briefs ORDER BY rowid DESC LIMIT 1")
            items = json.loads(brief["items_json"])
            items.append(
                {
                    "kind": "reference",
                    "text": "这一次的报告只列三条；交付之后不要当成默认偏好。",
                    "sourceIds": [ids[1][0]],
                }
            )
            db.execute(
                "UPDATE context_briefs SET items_json=? WHERE id=?", (encoded(items), brief["id"])
            )

        await store.call(add_reference, write=True)
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "arithmetic", "计算 17 加 25，只回答结果。"
        )
        plan = await runtime.context.project(
            "alice",
            c["id"],
            through_turn=receipt["turnId"],
            request_context={"instructions": "test", "catalog": [], "contextMaintenance": True},
        )
        assert plan["workingBriefId"] and "只列三条" not in str(plan["messages"])
    finally:
        await runtime.close()


async def test_capacity_compaction_still_wins_after_an_earlier_maintenance_brief(store):
    from test_context_provider import SummaryModel

    runtime, c, _, _ = await home_fixture(store)
    try:
        await maintain_all(runtime)
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "capacity", "Current request must survive"
        )
        runtime.context.model = SummaryModel()
        job = await runtime.context.request(
            "alice", c["id"], "capacity-fallback", automatic=True, target_tokens=100
        )
        await runtime.context.run(job["id"])
        plan = await runtime.context.project(
            "alice",
            c["id"],
            through_turn=receipt["turnId"],
            request_context={"instructions": "test", "catalog": [], "contextMaintenance": True},
        )
        assert plan["snapshotId"] and plan["workingBriefId"] is None
        assert plan["messages"][-1]["content"] == "Current request must survive"
    finally:
        await runtime.close()


async def test_scheduler_cancellation_requeues_a_running_handoff(store):
    runtime, _c, model, _ = await home_fixture(store, count=5)
    model.gate = asyncio.Event()
    running = None
    try:
        await drain_index(store)
        await runtime.context.maintenance.scan(force=True)
        job = (await queued(store))[0]
        running = asyncio.create_task(runtime.scheduler._job(job))
        await model.started.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert (
            await store.call(lambda db: row(db, "SELECT state FROM jobs WHERE id=?", (job["id"],)))
        )["state"] == "queued"
        assert not await store.call(lambda db: row(db, "SELECT id FROM context_briefs"))
    finally:
        model.gate.set()
        if running and not running.done():
            running.cancel()
        await runtime.close()


def test_replacing_one_constraint_keeps_other_requirements_from_the_same_message():
    source = [
        {
            "id": "old",
            "role": "user",
            "content_json": encoded({"text": "Do not deploy. Keep phone verification."}),
        },
        {
            "id": "new",
            "role": "user",
            "content_json": encoded(
                {
                    "text": "The deployment restriction is removed. Phone verification is still required."
                }
            ),
        },
    ]
    previous = [
        {"kind": "constraint", "text": text, "sourceIds": ["old"]}
        for text in ["Do not deploy", "Keep phone verification"]
    ]
    candidate = {
        "reviewedUserIds": ["new"],
        "items": [],
        "archives": {"day": "reference"},
        "superseded": [
            {
                "sourceId": "old",
                "previousQuote": "Do not deploy",
                "replacementSourceId": "new",
                "quote": "The deployment restriction is removed.",
            }
        ],
    }
    items, _ = validate_candidate(candidate, previous, source, source[1:], {"day"})
    assert [item["text"] for item in items] == ["Keep phone verification"]
    candidate["superseded"] = []
    retained, _ = validate_candidate(candidate, previous, source, source[1:], {"day"})
    assert retained == previous


async def test_twenty_recent_complete_rounds_and_current_tool_protocol_stay_intact(store):
    runtime, c, _, ids = await home_fixture(store)
    try:

        def recent(db):
            db.execute(
                "UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms() - 700_000, c["id"])
            )
            db.execute(
                "UPDATE messages SET created_ms=? WHERE branch_id=?",
                (now_ms(), c["active_branch_id"]),
            )
            db.execute(
                "UPDATE turns SET created_ms=?,finished_ms=? WHERE branch_id=?",
                (now_ms(), now_ms() - 700_000, c["active_branch_id"]),
            )

        await store.call(recent, write=True)
        await maintain_all(runtime)
        receipt = await runtime.conversations.accept(
            "alice", c["id"], "tool-round", "CURRENT_FULL_USER_REQUEST"
        )

        def tools(db):
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {
                    "tool_calls": [
                        {
                            "id": "current-call",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ]
                },
                turn_id=receipt["turnId"],
            )
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "tool",
                {"tool_call_id": "current-call", "text": "CURRENT_FULL_RESULT" * 2000},
                turn_id=receipt["turnId"],
            )

        await store.call(tools, write=True)
        plan = await runtime.context.project(
            "alice",
            c["id"],
            through_turn=receipt["turnId"],
            request_context={"instructions": "test", "catalog": [], "contextMaintenance": True},
        )
        assert plan["workingBriefId"] and len(plan["messages"]) == 44
        assert ids[0][0] not in plan["modelSourceMessageIds"]
        assert ids[6][0] in plan["modelSourceMessageIds"]
        current = plan["messages"][plan["currentTurnStart"] :]
        assert current[0]["content"] == "CURRENT_FULL_USER_REQUEST"
        assert current[1]["tool_calls"][0]["id"] == current[2]["tool_call_id"]
        assert current[2]["content"] == "CURRENT_FULL_RESULT" * 2000
    finally:
        await runtime.close()


async def test_daily_job_does_not_block_idle_handoff_without_new_messages(store):
    runtime, c, model, _ = await home_fixture(store, count=5)
    try:
        await maintain_all(runtime)
        before = await store.call(
            lambda db: row(
                db, "SELECT source_count FROM context_briefs ORDER BY rowid DESC LIMIT 1"
            )
        )
        assert before["source_count"] == 6
        calls = len(model.calls)
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET finished_ms=? WHERE branch_id=?",
                (now_ms() - 700_000, c["active_branch_id"]),
            ),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms() - 700_000, c["id"])
            ),
            write=True,
        )
        await maintain_all(runtime)
        after = await store.call(
            lambda db: row(
                db, "SELECT source_count FROM context_briefs ORDER BY rowid DESC LIMIT 1"
            )
        )
        assert after["source_count"] == 10 and len(model.calls) == calls + 1
        await maintain_all(runtime)
        assert len(model.calls) == calls + 1
    finally:
        await runtime.close()


async def test_recent_activity_and_queued_turns_do_not_count_as_idle(store):
    runtime, c, model, _ = await home_fixture(store, count=2)
    try:
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET finished_ms=? WHERE branch_id=?",
                (now_ms() - 700_000, c["active_branch_id"]),
            ),
            write=True,
        )
        await runtime.context.maintenance.scan(force=True)
        assert not await queued(store) and not model.calls
        await runtime.conversations.accept("alice", c["id"], "active-request", "Still working")
        await store.call(
            lambda db: db.execute(
                "UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms() - 700_000, c["id"])
            ),
            write=True,
        )
        await runtime.context.maintenance.scan(force=True)
        assert not await queued(store) and not model.calls
    finally:
        await runtime.close()


async def test_an_older_turn_finishing_later_advances_the_maintenance_trigger(store):
    runtime, _c, model, ids = await home_fixture(store, count=3)
    try:
        old_turn = (
            await store.call(
                lambda db: row(db, "SELECT turn_id FROM messages WHERE id=?", (ids[0][0],))
            )
        )["turn_id"]
        await store.call(
            lambda db: db.execute("UPDATE turns SET state='queued' WHERE id=?", (old_turn,)),
            write=True,
        )
        await maintain_all(runtime)
        assert not model.calls
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET state='completed',finished_ms=? WHERE id=?", (now_ms(), old_turn)
            ),
            write=True,
        )
        await maintain_all(runtime)
        assert model.calls
        brief = await store.call(
            lambda db: row(
                db, "SELECT source_count FROM context_briefs ORDER BY rowid DESC LIMIT 1"
            )
        )
        assert brief["source_count"] == 2
    finally:
        await runtime.close()


async def test_an_interrupted_attempt_inside_a_completed_round_does_not_block_handoff(store):
    runtime, c, model, ids = await home_fixture(store, count=5)
    try:
        tid = (
            await store.call(
                lambda db: row(db, "SELECT turn_id FROM messages WHERE id=?", (ids[0][0],))
            )
        )["turn_id"]
        partial = await store.call(
            lambda db: message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {"text": "Partial attempt, outcome unknown"},
                turn_id=tid,
                status="interrupted",
            ),
            write=True,
        )
        await maintain_all(runtime)
        assert model.calls
        assert await store.call(lambda db: row(db, "SELECT id FROM context_briefs"))
        sources = await store.call(lambda db: rows(db, "SELECT sources_json FROM period_summaries"))
        assert any(
            source["messageId"] == partial and source["status"] == "interrupted"
            for part in sources
            for source in json.loads(part["sources_json"])
        )
    finally:
        await runtime.close()
