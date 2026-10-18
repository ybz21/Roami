"""Opt-in evaluations stay bounded, traceable and independent of the Main queue."""

import asyncio
import json

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


class SuggestionModel:
    model = "suggestion-fixture"

    def __init__(self, output=None):
        self.output = (
            output or '{"send":true,"text":"Consider checking the result against your goal."}'
        )
        self.calls = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def stream(self, messages, tools):
        assert tools == []
        self.calls.append(messages)
        self.entered.set()
        await self.release.wait()
        yield ModelEvent("text", self.output)
        yield ModelEvent(
            "usage",
            {
                "inputTokens": 12,
                "outputTokens": 4,
                "providerRaw": {"diagnostic": "private-fixture"},
            },
        )


async def verified(task, result):
    return True


async def enable(runtime, owner="alice", *, hourly=1):
    settings = await runtime.notification_policy.get(owner)
    settings["enabled"]["suggestion"] = True
    settings["maxSuggestionsPerHour"] = hourly
    await runtime.notification_policy.replace(owner, settings)


async def completed_task(runtime, owner="alice", key="one"):
    conversation = await runtime.conversations.create(owner)
    task = await runtime.tasks.create(
        owner,
        conversation["id"],
        "Research the goal",
        key=key,
        executor="codex",
        record_intent=True,
    )
    run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    await runtime.tasks.report(
        owner, task["id"], run["id"], 1, {"state": "succeeded", "summary": "Independent evidence"}
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task["id"],)
        )
    )
    await runtime.dispatch.verify(job)
    return conversation, task


async def evaluations(store):
    return await store.call(
        lambda db: rows(db, "SELECT * FROM jobs WHERE kind='proactive.evaluate' ORDER BY rowid")
    )


async def suggestions(store):
    return await store.call(
        lambda db: rows(
            db, "SELECT * FROM messages WHERE json_extract(content_json,'$.source')='suggestion'"
        )
    )


async def test_event_evaluation_publishes_one_traced_message_and_outbox(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    runtime.proactive.model = model
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        conversation, task = await completed_task(runtime)
        await runtime.proactive.tick()
        await runtime.proactive.tick()
        assert len(model.calls) == 1
        notices = await suggestions(store)
        assert len(notices) == 1 and notices[0]["conversation_id"] == conversation["id"]
        content = json.loads(notices[0]["content_json"])
        assert content["sourceMessageIds"] == [task["origin_message_id"]]
        jobs = await evaluations(store)
        assert jobs[0]["state"] == "done" and jobs[0]["attempts"] == 1
        payload = json.loads(jobs[0]["payload_json"])
        assert payload["sent"] and len(payload["promptSha256"]) == 64
        assert payload["usage"] == {"inputTokens": 12, "outputTokens": 4}
        assert "private-fixture" not in jobs[0]["payload_json"]
        assert payload["eventId"] == content["sourceEventId"]
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM deliveries d JOIN events e ON e.id=d.event_id WHERE e.message_id=?",
                    (notices[0]["id"],),
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


async def test_default_opt_out_and_initial_watermark_do_not_evaluate_archive(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    runtime.proactive.model = model
    try:
        await completed_task(runtime, key="archive")
        await runtime.proactive.recover()
        await runtime.proactive.tick()
        await completed_task(runtime, key="opted-out")
        await runtime.proactive.tick()
        await enable(runtime)
        await runtime.proactive.tick()
        assert model.calls == [] and await evaluations(store) == []
        assert runtime.settings.proactive_enabled is False
    finally:
        await runtime.close()


async def test_silence_and_failures_consume_owner_hourly_and_daily_evaluation_budget(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel('{"send":false,"text":""}')
    runtime.proactive.model = model
    runtime.proactive.daily_budget = 2
    clock = [now_ms()]
    runtime.proactive.clock = lambda: clock[0]
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        for key in ["one", "two", "three"]:
            await completed_task(runtime, key=key)
        await runtime.proactive.tick()
        await runtime.proactive.tick()
        assert len(model.calls) == 1
        clock[0] += 3_600_001
        model.output = "invalid JSON"
        await runtime.proactive.tick()
        assert len(model.calls) == 2
        clock[0] += 3_600_001
        await runtime.proactive.tick()
        assert len(model.calls) == 2
        assert [job["state"] for job in await evaluations(store)] == ["done", "failed", "queued"]
        assert await suggestions(store) == []
        clock[0] += 86_400_001
        await runtime.proactive.tick()
        assert len(model.calls) == 2
        assert (await evaluations(store))[-1]["state"] == "done"
    finally:
        await runtime.close()


@pytest.mark.parametrize("change", ["forget", "disable", "revise"])
async def test_source_and_preference_are_rechecked_after_generation(store, change):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    model.release.clear()
    runtime.proactive.model = model
    handle = None
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        _, task = await completed_task(runtime)
        handle = asyncio.create_task(runtime.proactive.tick())
        await asyncio.wait_for(model.entered.wait(), 3)
        if change == "forget":
            memory = await runtime.memory.save(
                "alice", "Private", "Research the goal", task["origin_message_id"]
            )
            await runtime.memory.forget("alice", memory["id"])
        elif change == "disable":
            settings = await runtime.notification_policy.get("alice")
            settings["enabled"]["suggestion"] = False
            await runtime.notification_policy.replace("alice", settings)
        else:
            await store.call(
                lambda db: db.execute(
                    "UPDATE tasks SET revision=revision+1 WHERE id=?", (task["id"],)
                ),
                write=True,
            )
        model.release.set()
        await handle
        assert await suggestions(store) == []
        assert json.loads((await evaluations(store))[0]["payload_json"])["skipped"]
    finally:
        model.release.set()
        if handle:
            await asyncio.gather(handle, return_exceptions=True)
        await runtime.close()


async def test_forgetting_after_publication_excludes_suggestion_and_delivery(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    runtime.proactive.model = SuggestionModel()
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        conversation, task = await completed_task(runtime)
        await runtime.proactive.tick()
        notice = (await suggestions(store))[0]
        memory = await runtime.memory.save(
            "alice", "Private", "Research the goal", task["origin_message_id"]
        )
        await runtime.memory.forget("alice", memory["id"])
        omitted = await store.call(
            lambda db: row(
                db, "SELECT * FROM context_omissions WHERE message_id=?", (notice["id"],)
            )
        )
        assert omitted
        projected = await runtime.context.project("alice", conversation["id"])
        assert "Consider checking" not in json.dumps(projected["messages"])
        await runtime.deliveries.claim("alice")
        delivery = await store.call(
            lambda db: row(
                db,
                "SELECT d.* FROM deliveries d JOIN events e ON e.id=d.event_id WHERE e.message_id=?",
                (notice["id"],),
            )
        )
        assert delivery["state"] != "sending"
    finally:
        await runtime.close()


async def test_cancelled_generation_is_not_replayed_after_restart(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    model.release.clear()
    runtime.proactive.model = model
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        await completed_task(runtime)
        handle = asyncio.create_task(runtime.proactive.tick())
        await asyncio.wait_for(model.entered.wait(), 3)
        handle.cancel()
        await asyncio.gather(handle, return_exceptions=True)
        await runtime.proactive.recover()
        await runtime.proactive.tick()
        assert len(model.calls) == 1 and await suggestions(store) == []
        job = (await evaluations(store))[0]
        assert job["state"] == "failed" and json.loads(job["payload_json"])["generationUnknown"]
    finally:
        model.release.set()
        await runtime.close()


@pytest.mark.parametrize(
    "output",
    [
        '{"send":"true","text":"suggestion"}',
        '{"send":true,"text":""}',
        '{"send":true,"text":"suggestion","runShell":"whoami"}',
        "not JSON",
        "x" * 6001,
    ],
)
async def test_invalid_model_result_is_not_published_or_retried(store, output):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel(output)
    runtime.proactive.model = model
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        await completed_task(runtime)
        await runtime.proactive.tick()
        await runtime.proactive.tick()
        assert len(model.calls) == 1 and await suggestions(store) == []
        assert (await evaluations(store))[0]["state"] == "failed"
    finally:
        await runtime.close()


async def test_recovery_fences_late_generation_and_does_not_replay_it(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    model.release.clear()
    runtime.proactive.model = model
    handle = None
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        await completed_task(runtime)
        handle = asyncio.create_task(runtime.proactive.tick())
        await asyncio.wait_for(model.entered.wait(), 3)
        await runtime.proactive.recover()
        model.release.set()
        await handle
        await runtime.proactive.tick()
        assert len(model.calls) == 1 and await suggestions(store) == []
        job = (await evaluations(store))[0]
        assert job["state"] == "failed" and json.loads(job["payload_json"])["generationUnknown"]
    finally:
        model.release.set()
        if handle:
            await asyncio.gather(handle, return_exceptions=True)
        await runtime.close()


async def test_owner_budget_does_not_block_another_owners_evaluation(store):
    runtime = Runtime(store, ConversationModel(), verifier=verified)
    model = SuggestionModel()
    runtime.proactive.model = model
    runtime.proactive.daily_budget = 1
    try:
        await runtime.proactive.recover()
        await enable(runtime)
        await enable(runtime, "bob")
        await completed_task(runtime, key="alice-one")
        await runtime.proactive.tick()
        await completed_task(runtime, key="alice-two")
        bob, _ = await completed_task(runtime, "bob", "bob-one")
        await runtime.proactive.tick()
        assert len(model.calls) == 2
        assert len(await suggestions(store)) == 2
        assert (await suggestions(store))[-1]["conversation_id"] == bob["id"]
    finally:
        await runtime.close()


async def test_blocked_background_evaluation_does_not_occupy_main_slot(store):
    runtime = Runtime(
        store, ConversationModel(), verifier=verified, settings=Settings(proactive_enabled=True)
    )
    model = SuggestionModel()
    model.release.clear()
    runtime.proactive.model = model
    await runtime.start()
    try:
        await enable(runtime)
        conversation, _ = await completed_task(runtime)
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
        assert view["messages"][-1]["content"]["text"] == "Answer: quick question"
    finally:
        model.release.set()
        await runtime.close()


@pytest.mark.parametrize(
    "configuration",
    [
        "enabled=1",
        "daily_budget=true",
        "daily_budget=0",
        "daily_budget=11",
        "timeout_seconds=false",
        "timeout_seconds=0",
        "timeout_seconds=31",
    ],
)
def test_invalid_proactive_configuration_is_rejected(tmp_path, configuration):
    path = tmp_path / "agent.toml"
    path.write_text("[proactive]\n" + configuration)
    with pytest.raises(DomainError, match="INVALID_PROACTIVE_CONFIG"):
        Settings.load(path)
