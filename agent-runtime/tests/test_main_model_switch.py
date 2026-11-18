"""Main can change model between requests without replaying tools or cancelling a stream."""

import asyncio

import httpx
import pytest
from test_model_settings import Model
from test_runtime import GatedModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.protocol.models import ModelEvent
from roami_agent.providers.live_model import LiveModel
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.server.model_settings import load_model_settings
from roami_agent.storage.database import row


def configured_runtime(store, model=None):
    runtime = Runtime(
        store,
        model or Model(),
        settings=Settings(endpoint="http://127.0.0.1:1/v1", model="initial"),
    )
    runtime.model_settings.factory = lambda settings, role: Model(settings.route(role).name)
    return runtime


async def completed(store, receipt):
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
        ),
    )


async def test_http_switch_during_stream_keeps_partial_history_and_worker(store):
    old = GatedModel()
    runtime = configured_runtime(store, old)
    await runtime.start()
    try:
        c = await runtime.conversations.create("local")
        first = await runtime.chat.submit("local", c["id"], "first", "first question")
        await asyncio.wait_for(old.entered.wait(), 5)
        worker = runtime.worker_model
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://fixture",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            response = await client.put("/v1/model-settings", json={"main": {"model": "next"}})
        assert response.status_code == 200
        assert runtime.worker_model is worker
        assert runtime.settings.route("worker").name == "initial"
        assert not runtime.turn_tasks[first["turnId"]].done()
        old.release.set()
        await completed(store, first)
        second = await runtime.chat.submit("local", c["id"], "second", "second question")
        await completed(store, second)
        view = await runtime.conversations.messages("local", c["id"])
        assert view["branchId"] == c["active_branch_id"]
        assert "first answer" in view["messages"][-3]["content"]["text"]
        assert view["messages"][-1]["content"]["text"] == "next"
        assert all(t["state"] == "completed" for t in view["turns"])
        assert load_model_settings(runtime.model_settings.base, store.data_root).model == "next"
        events = await runtime.conversations.events("local", c["id"])
        assert any(e["kind"] == "model.changed" for e in events)
    finally:
        old.release.set()
        await runtime.close()


async def test_same_turn_uses_new_model_after_tool_without_replaying_it(store):
    invoked = []

    class ToolModel(Model):
        async def stream(self, messages, tools):
            yield ModelEvent(
                "tool",
                {
                    "id": "read-once",
                    "type": "function",
                    "function": {"name": "memory_search", "arguments": '{"query":"facts"}'},
                },
            )

    old = ToolModel("old")
    new = Model("new")
    runtime = configured_runtime(store, old)
    runtime.model_settings.factory = lambda settings, role: new
    original = runtime.gateway.invoke

    async def invoke(turn, mid, call, role, binding):
        invoked.append(call["id"])
        value = await original(turn, mid, call, role, binding)
        await runtime.model_settings.save("local", {"main": {"model": "new"}})
        return value

    runtime.gateway.invoke = invoke
    await runtime.start()
    try:
        c = await runtime.conversations.create("local")
        result = await runtime.chat.submit("local", c["id"], "question", "Find facts")
        await completed(store, result)
        assert invoked == ["read-once"]
        manifests = await store.call(
            lambda db: list(
                db.execute(
                    "SELECT model_key FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
                    (result["turnId"],),
                )
            )
        )
        assert [m[0] for m in manifests] == ["old", "new"]
        view = await runtime.conversations.messages("local", c["id"])
        assert view["messages"][-1]["content"]["text"] == "new"
        assert sum(m["role"] == "tool" for m in view["messages"]) == 1
    finally:
        await runtime.close()


async def test_provider_drains_after_lease_and_multiple_switches_close_each_once():
    class ClosingModel(Model):
        closes = 0

        async def close(self):
            self.closes += 1
            await super().close()

    initial, first, second, third = [
        ClosingModel(name) for name in ["initial", "first", "second", "third"]
    ]
    live = LiveModel(initial)
    await live.replace(first)
    with live.lease() as selected:
        await live.replace(second)
        await live.replace(third)
        assert selected is first and not first.closed
        assert second.closed and not third.closed
    await live.close()
    assert not initial.closed
    assert [first.closes, second.closes, third.closes] == [1, 1, 1]
    assert not live.retired


async def test_commands_are_scoped_idempotent_and_create_no_turn(store):
    runtime = configured_runtime(store)
    try:
        c = await runtime.conversations.create("local")
        assert (await runtime.chat.submit("local", c["id"], "picker", "/model"))[
            "action"
        ] == "model"
        receipt = await runtime.chat.submit("local", c["id"], "model-one", "/model first")
        await runtime.chat.submit("local", c["id"], "model-two", "/model second")
        assert await runtime.chat.submit("local", c["id"], "model-one", "/model first") == receipt
        assert runtime.model.model == "second"
        with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
            await runtime.chat.submit("local", c["id"], "model-one", "/model third")
        with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
            await runtime.chat.submit("local", "missing", "missing", "/model third")
        other = await runtime.conversations.create("other")
        with pytest.raises(DomainError, match="MODEL_SETTINGS_FORBIDDEN"):
            await runtime.chat.submit("other", other["id"], "forbidden", "/model third")
        view = await runtime.conversations.messages("local", c["id"])
        assert view["turns"] == [] and view["messages"] == []
    finally:
        await runtime.close()


async def test_invalid_switch_leaves_saved_route_and_provider_untouched(store):
    runtime = configured_runtime(store)
    try:
        await runtime.model_settings.save("local", {"main": {"model": "first"}})
        first = runtime.model.current
        with pytest.raises(DomainError, match="INVALID_MODEL_CONFIG"):
            await runtime.model_settings.save("local", {"main": {"model": "bad\nmodel"}})
        assert runtime.model.current is first and not first.closed
        assert load_model_settings(runtime.model_settings.base, store.data_root).model == "first"
    finally:
        await runtime.close()


async def test_admission_race_rebuilds_with_new_route_without_a_failed_turn(store):
    class RejectedModel(Model):
        async def stream(self, messages, tools):
            await runtime.model_settings.save("local", {"main": {"model": "next"}})
            raise ModelAdmissionRejected("MODEL_GATEWAY_ROUTE_CHANGED", 409)
            yield

    runtime = configured_runtime(store, RejectedModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("local")
        result = await runtime.chat.submit("local", c["id"], "first", "hello")
        await completed(store, result)
        view = await runtime.conversations.messages("local", c["id"])
        assert [m["content"]["text"] for m in view["messages"]] == ["hello", "next"]
        events = await runtime.conversations.events("local", c["id"])
        assert any(e["kind"] == "message.discarded" for e in events)
        assert not any(e["kind"] in {"turn.failed", "turn.interrupted"} for e in events)
    finally:
        await runtime.close()


async def test_hot_main_change_preserves_busy_worker_and_background_jobs(store):
    runtime = configured_runtime(store)
    try:
        worker = runtime.worker_model
        vision = runtime.loop.context.vision
        runtime.active["busy-worker"] = {"handle": asyncio.current_task()}
        await runtime.briefs.lock.acquire()
        await runtime.model_settings.save(
            "local", {"main": {"model": "next", "reasoningEffort": None}}
        )
        assert runtime.worker_model is worker
        assert runtime.briefs.model is worker and runtime.proactive.model is worker
        assert runtime.loop.context.vision is vision
        assert runtime.model.model == "next"
    finally:
        runtime.active.clear()
        runtime.briefs.lock.release()
        await runtime.close()


async def test_unknown_transport_outcome_is_never_replayed_after_a_switch(store):
    class FailedModel(Model):
        async def stream(self, messages, tools):
            await runtime.model_settings.save("local", {"main": {"model": "next"}})
            raise DomainError("MODEL_TRANSPORT_FAILED", 502)
            yield

    runtime = configured_runtime(store, FailedModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("local")
        result = await runtime.chat.submit("local", c["id"], "first", "hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='failed'", (result["turnId"],)
            ),
        )
        manifests = await store.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM prompt_manifests WHERE turn_id=?", (result["turnId"],)
            ).fetchone()[0]
        )
        assert manifests == 1
    finally:
        await runtime.close()


async def test_context_consumer_retries_only_unadmitted_stale_provider():
    class RetiredModel(Model):
        async def stream(self, messages, tools):
            await live.replace(Model("next"))
            raise ModelAdmissionRejected("MODEL_GATEWAY_ROUTE_CHANGED", 409)
            yield

    live = LiveModel(RetiredModel())
    try:
        assert [part.value async for part in live.stream([], [])] == ["next"]
    finally:
        await live.close()


async def test_context_consumer_does_not_replay_partial_output():
    class PartialModel(Model):
        async def stream(self, messages, tools):
            yield ModelEvent("text", "partial")
            await live.replace(Model("next"))
            raise ModelAdmissionRejected("MODEL_GATEWAY_ROUTE_CHANGED", 409)

    live = LiveModel(PartialModel())
    seen = []
    try:
        with pytest.raises(ModelAdmissionRejected):
            async for part in live.stream([], []):
                seen.append(part.value)
        assert seen == ["partial"]
    finally:
        await live.close()
