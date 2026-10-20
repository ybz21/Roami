"""Daily briefs persist explicit schedules, bounded sources and generation receipts."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.daily_briefs import DailyBriefs
from roami_agent.memory.records import Memories
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import rows


def instant(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


class BriefModel:
    model = "daily-brief-fixture"

    def __init__(self):
        self.calls = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def stream(self, messages, tools):
        assert tools == []
        self.calls.append(messages)
        self.entered.set()
        await self.release.wait()
        yield ModelEvent(
            "text", '{"text":"2026-10-17: You requested research; completion is not recorded."}'
        )


async def fixture(store):
    now = [instant("2026-10-17T00:00:00")]
    model = BriefModel()
    briefs = DailyBriefs(store, model, clock=lambda: now[0])
    conversations = Conversations(store)
    conversation = await conversations.create("alice")
    message = await conversations.accept("alice", conversation["id"], "source", "Research a topic")
    await store.call(
        lambda db: db.execute(
            "UPDATE events SET created_ms=? WHERE message_id=?", (now[0], message["messageId"])
        ),
        write=True,
    )
    schedule = await briefs.create(
        "alice",
        conversation["id"],
        "Summarize yesterday's recorded work",
        "daily",
        daily_at="08:00",
        timezone_name="Asia/Shanghai",
    )
    now[0] = instant("2026-10-18T00:00:00")
    return briefs, model, now, conversation, message, schedule


async def test_due_brief_is_once_per_calendar_firing_and_preserves_source_intent(store):
    briefs, model, now, conversation, source, schedule = await fixture(store)
    assert await briefs.list("bob") == []
    await briefs.tick()
    await briefs.tick()
    assert len(model.calls) == 1
    data = json.loads(model.calls[0][-1]["content"])
    assert data["dayKey"] == "2026-10-17" and data["timezone"] == "Asia/Shanghai"
    assert data["records"][0]["kind"] == "message.accepted"
    assert data["records"][0]["text"] == "Research a topic"
    history = await Conversations(store).messages("alice", conversation["id"])
    notice = history["messages"][-1]
    assert notice["content"]["sourceMessageIds"] == [source["messageId"]]
    assert notice["content"]["briefDayKey"] == "2026-10-17"
    listed = (await briefs.list("alice"))[0]
    assert listed["nextDueMs"] == instant("2026-10-19T00:00:00")
    assert listed["lastGeneration"]["state"] == "done"
    assert listed["lastGeneration"]["messageId"] == notice["id"]
    with pytest.raises(DomainError, match="BRIEF_NOT_FOUND"):
        await briefs.cancel("bob", schedule["id"])
    await briefs.cancel("alice", schedule["id"])
    now[0] += 86_400_000
    await briefs.tick()
    assert len(model.calls) == 1
    assert not (await briefs.list("alice"))[0]["enabled"]


async def test_schedule_key_conflicts_and_cancelled_retries_do_not_reenable(store):
    briefs, _, _, conversation, _, schedule = await fixture(store)
    retry = await briefs.create(
        "alice",
        conversation["id"],
        "Summarize yesterday's recorded work",
        "daily",
        daily_at="08:00",
        timezone_name="Asia/Shanghai",
    )
    assert retry["id"] == schedule["id"]
    with pytest.raises(DomainError, match="BRIEF_KEY_CONFLICT"):
        await briefs.create(
            "alice",
            conversation["id"],
            "Different scope",
            "daily",
            daily_at="08:00",
            timezone_name="Asia/Shanghai",
        )
    await briefs.cancel("alice", schedule["id"])
    retry = await briefs.create(
        "alice",
        conversation["id"],
        "Summarize yesterday's recorded work",
        "daily",
        daily_at="08:00",
        timezone_name="Asia/Shanghai",
    )
    assert retry["enabled"] is False


@pytest.mark.parametrize("change", ["cancel", "forget"])
async def test_cancel_and_forgetting_fence_inflight_brief_publication(store, change):
    briefs, model, _, conversation, source, schedule = await fixture(store)
    model.release.clear()
    handle = asyncio.create_task(briefs.tick())
    try:
        await asyncio.wait_for(model.entered.wait(), 3)
        if change == "cancel":
            await briefs.cancel("alice", schedule["id"])
        else:
            memory = Memories(store)
            saved = await memory.save("alice", "Private", "Research a topic", source["messageId"])
            await memory.forget("alice", saved["id"])
        model.release.set()
        await handle
        messages = await Conversations(store).messages("alice", conversation["id"])
        assert len(messages["messages"]) == 1
        assert (await briefs.list("alice"))[0]["lastGeneration"]["skipped"]
    finally:
        model.release.set()
        await asyncio.gather(handle, return_exceptions=True)


async def test_crashed_generation_is_not_replayed_but_next_daily_firing_is_distinct(store):
    briefs, model, now, _, _, _ = await fixture(store)
    await store.call(briefs._due, write=True)
    assert await store.call(briefs._claim, write=True)
    await briefs.recover()
    await briefs.tick()
    assert model.calls == []
    previous = (await briefs.list("alice"))[0]["lastGeneration"]
    assert previous["state"] == "failed" and previous["generationUnknown"]
    now[0] += 86_400_000
    await briefs.tick()
    assert len(model.calls) == 1
    assert (await briefs.list("alice"))[0]["lastGeneration"]["dayKey"] == "2026-10-18"


async def test_catch_up_generates_latest_local_day_instead_of_replaying_missed_days(store):
    briefs, model, now, _, _, _ = await fixture(store)
    now[0] = instant("2026-10-23T00:00:00")
    await briefs.tick()
    assert len(model.calls) == 1
    assert json.loads(model.calls[0][-1]["content"])["dayKey"] == "2026-10-22"
    jobs = await store.call(lambda db: rows(db, "SELECT * FROM jobs WHERE kind='brief.generate'"))
    assert len(jobs) == 1


async def test_brief_keeps_original_branch_after_user_forks_conversation(store):
    briefs, _, _, conversation, _, _ = await fixture(store)
    branch = "other-branch"
    await store.call(
        lambda db: db.execute(
            "INSERT INTO branches(id,conversation_id,created_ms) VALUES(?,?,?)",
            (branch, conversation["id"], instant("2026-10-18T00:00:00")),
        ),
        write=True,
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE conversations SET active_branch_id=? WHERE id=?", (branch, conversation["id"])
        ),
        write=True,
    )
    await briefs.tick()
    original = await Conversations(store).messages(
        "alice", conversation["id"], conversation["active_branch_id"]
    )
    assert original["messages"][-1]["content"].get("briefDayKey") == "2026-10-17"
    active = await Conversations(store).messages("alice", conversation["id"])
    assert active["messages"] == []


async def test_http_daily_brief_uses_existing_reminder_list_and_scoped_cancellation(store):
    import httpx
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            payload = {
                "conversationId": conversation["id"],
                "requestKey": "brief",
                "text": "Daily brief",
                "kind": "daily_brief",
                "dailyAt": "08:00",
                "timezone": "Asia/Shanghai",
            }
            created = await client.post("/v1/reminders", json=payload)
            assert created.status_code == 200
            identifier = created.json()["data"]["id"]
            assert identifier.startswith("brief:")
            record = (await client.get("/v1/reminders")).json()["data"][0]
            assert record["id"] == identifier and record["spec"]["kind"] == "daily_brief"
            assert (await client.get("/v1/reminders", headers={"X-Roami-Owner": "bob"})).json()[
                "data"
            ] == []
            assert (
                await client.delete("/v1/reminders/" + identifier, headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
            assert (
                await client.post(
                    "/v1/reminders", json=dict(payload, requestKey="invalid", afterSeconds=10)
                )
            ).status_code == 400
            assert (await client.delete("/v1/reminders/" + identifier)).json()["data"][
                "enabled"
            ] is False
    finally:
        await runtime.close()


async def test_main_schedules_daily_brief_through_existing_reminder_tool(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    class MainModel(ConversationModel):
        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                receipt = json.loads(messages[-1]["content"])
                assert receipt["id"].startswith("brief:") and receipt["enabled"]
                yield ModelEvent("text", "Daily brief scheduled.")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "brief-create",
                        "type": "function",
                        "function": {
                            "name": "reminder_create",
                            "arguments": json.dumps(
                                {
                                    "kind": "daily_brief",
                                    "text": "Summarize yesterday's recorded work",
                                    "dailyAt": "08:00",
                                    "timezone": "Asia/Shanghai",
                                }
                            ),
                        },
                    },
                )

    runtime = Runtime(
        store, MainModel(), worker_model=BriefModel(), memory_model=ConversationModel()
    )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "schedule", "Give me a daily brief at 8am Shanghai time"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        schedules = await runtime.briefs.list("alice")
        assert len(schedules) == 1 and schedules[0]["spec"]["timezone"] == "Asia/Shanghai"
        assert await runtime.tasks.list("alice") == []
    finally:
        await runtime.close()


async def test_brief_generation_does_not_block_main_and_shutdown_records_unknown_generation(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    briefs, model, _, conversation, _, _ = await fixture(store)
    model.release.clear()
    runtime = Runtime(store, ConversationModel())
    runtime.briefs = briefs
    await runtime.start()
    try:
        await asyncio.wait_for(model.entered.wait(), 3)
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "question", "quick question"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        assert not model.release.is_set()
        view = await runtime.conversations.messages("alice", conversation["id"])
        # The fixture's older intake may resume and append a streaming message after this reply.
        replies = [
            message
            for message in view["messages"]
            if message["turn_id"] == receipt["turnId"]
            and message["role"] == "assistant"
            and message["status"] == "completed"
        ]
        assert len(replies) == 1 and replies[0]["content"]["text"] == "Answer: quick question"
    finally:
        await runtime.close()
    last = (await briefs.list("alice"))[0]["lastGeneration"]
    assert last["state"] == "failed" and last["generationUnknown"]


async def test_publication_receipt_failure_rolls_back_message_and_outbox_without_replay(store):
    briefs, model, _, conversation, _, _ = await fixture(store)
    await store.call(
        lambda db: db.execute(
            "CREATE TRIGGER brief_receipt_failure BEFORE UPDATE ON jobs WHEN OLD.kind='brief.generate' AND NEW.state='done' BEGIN SELECT RAISE(ABORT,'private-fixture'); END"
        ),
        write=True,
    )
    await briefs.tick()
    await briefs.tick()
    assert len(model.calls) == 1
    view = await Conversations(store).messages("alice", conversation["id"])
    assert len(view["messages"]) == 1
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])
        == 0
    )
    last = (await briefs.list("alice"))[0]["lastGeneration"]
    assert last["state"] == "failed" and last["errorCode"] == "BRIEF_GENERATION_UNAVAILABLE"
    assert "private-fixture" not in json.dumps(last)


async def test_schedule_capacity_is_owner_scoped_and_cancel_releases_it(store):
    briefs, _, _, conversation, _, schedule = await fixture(store)
    briefs.daily_budget = 1
    with pytest.raises(DomainError, match="BRIEF_SCHEDULE_LIMIT"):
        await briefs.create(
            "alice", conversation["id"], "Another brief", "another", daily_at="09:00"
        )
    other = await Conversations(store).create("bob")
    assert (await briefs.create("bob", other["id"], "Bob's brief", "daily", daily_at="09:00"))[
        "enabled"
    ]
    await briefs.cancel("alice", schedule["id"])
    assert (
        await briefs.create(
            "alice", conversation["id"], "Another brief", "another", daily_at="09:00"
        )
    )["enabled"]


@pytest.mark.parametrize(
    "configuration",
    [
        "daily_budget=true",
        "daily_budget=0",
        "daily_budget=11",
        "timeout_seconds=false",
        "timeout_seconds=-1",
        'timeout_seconds="61"',
    ],
)
def test_invalid_brief_configuration_is_rejected(tmp_path, configuration):
    from roami_agent.server.configuration import Settings

    path = tmp_path / "agent.toml"
    path.write_text("[briefs]\n" + configuration)
    with pytest.raises(DomainError, match="INVALID_BRIEF_CONFIG"):
        Settings.load(path)
