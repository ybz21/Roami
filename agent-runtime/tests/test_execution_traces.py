"""Trace joins, timing fidelity and privacy across native and opaque execution."""

import asyncio
import json

import httpx
from test_runtime import ConversationModel, GatedModel, until
from test_task_cancellation import task_run

from roami_agent.app import Runtime
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def test_trace_joins_native_task_and_completion_without_another_user_turn(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "delegate research")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE trigger_kind='completion' AND state='completed'"
            ),
        )
        unrelated = await runtime.chat.submit("alice", c["id"], "other", "private unrelated prompt")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (unrelated["turnId"],)
            ),
        )
        task = (await runtime.tasks.list("alice", c["id"]))[0]
        trace = await runtime.traces.get("alice", turn_id=receipt["turnId"])
        by_task = await runtime.traces.get("alice", task_id=task["id"])
        assert by_task["traceId"] == trace["traceId"] == receipt["turnId"]
        assert trace["summary"]["modelCalls"] == 3
        assert not trace["summary"]["active"]
        assert {
            "agent.main",
            "agent.worker",
            "agent.report",
            "executor.native",
            "tool.delegate",
        } <= {s["name"] for s in trace["spans"]}
        identifiers = {s["spanId"] for s in trace["spans"]}
        assert all(
            s["parentSpanId"] in identifiers or s["parentSpanId"] is None for s in trace["spans"]
        )
        models = [s for s in trace["spans"] if s["name"] == "model.request"]
        assert all(
            s["attributes"]["timingSource"] == "measured" and s["durationMs"] >= 0 for s in models
        )
        child = next(s for s in trace["spans"] if s["name"] == "agent.worker")
        assert (await runtime.traces.get("alice", turn_id=child["attributes"]["turnId"]))[
            "traceId"
        ] == trace["traceId"]
        serialized = json.dumps(trace)
        assert (
            "delegate research" not in serialized and "private unrelated prompt" not in serialized
        )
        assert unrelated["turnId"] not in serialized
    finally:
        await runtime.close()


async def test_running_first_text_and_cancelled_model_timing_are_durable(store):
    model = GatedModel()
    runtime = Runtime(store, model)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "hello")
        await asyncio.wait_for(model.entered.wait(), 2)
        trace = await runtime.traces.get("alice", turn_id=receipt["turnId"])
        model_span = next(s for s in trace["spans"] if s["name"] == "model.request")
        assert model_span["state"] == "running" and model_span["finishedMs"] is None
        assert model_span["attributes"]["firstTextMs"] >= 0
        assert trace["summary"]["firstCommittedTextMs"] >= 0
        await runtime.chat.interrupt("alice", c["id"], "stop")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='interrupted'", (receipt["turnId"],)
            ),
        )
        trace = await runtime.traces.get("alice", turn_id=receipt["turnId"])
        model_span = next(s for s in trace["spans"] if s["name"] == "model.request")
        assert model_span["state"] == "interrupted"
        assert model_span["finishedMs"] is not None and not trace["summary"]["active"]
    finally:
        await runtime.close()


async def test_trace_owner_scope_http_and_perfetto_export(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "private prompt body")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
        ) as client:
            params = {"turnId": receipt["turnId"], "format": "chrome"}
            response = await client.get(
                "/v1/traces", params=params, headers={"X-Roami-Owner": "alice"}
            )
            assert response.status_code == 200
            export = response.json()["data"]
            assert export["traceEvents"] and export["displayTimeUnit"] == "ms"
            assert all(
                e["ph"] in {"X", "i", "M"} and isinstance(e["tid"], int)
                for e in export["traceEvents"]
            )
            assert "private prompt body" not in response.text
            assert (
                await client.get("/v1/traces", params=params, headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
            assert (
                await client.get(
                    "/v1/traces",
                    params={"turnId": receipt["turnId"], "taskId": "other"},
                    headers={"X-Roami-Owner": "alice"},
                )
            ).status_code == 400
    finally:
        await runtime.close()


async def test_legacy_timing_is_inferred_and_unknown_external_result_is_not_success(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE prompt_manifests SET parts_json=json_remove(parts_json,'$.timing')"
            ),
            write=True,
        )
        trace = await runtime.traces.get("alice", turn_id=receipt["turnId"])
        model = next(s for s in trace["spans"] if s["name"] == "model.request")
        assert model["attributes"]["timingSource"] == "message_lifecycle"
        assert model["attributes"]["firstTextMs"] is None
        runtime.scheduler.stopping = True
        await runtime.supervisor
        task, run = await task_run(runtime, c, "private task goal")
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET executor_kind='cli',state='unknown',started_ms=? WHERE id=?",
                (task["created_ms"], run["id"]),
            ),
            write=True,
        )
        trace = await runtime.traces.get("alice", task_id=task["id"])
        executor = next(s for s in trace["spans"] if s["name"] == "executor.cli")
        assert executor["state"] == "unknown" and executor["finishedMs"] is None
        assert executor["attributes"]["observationUnit"] == "turn"
        assert trace["summary"]["hasUnknown"] and trace["summary"]["active"]
        assert not trace["coverage"]["externalAgentInternals"]
        assert "private task goal" not in json.dumps(trace)
    finally:
        await runtime.close()


async def test_diagnostic_write_failure_does_not_repeat_or_fail_the_model(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    original = store.call

    async def fail_timing(fn, *, write=False):
        if (
            getattr(fn, "__code__", None)
            and fn.__code__.co_filename.endswith("prompt_manifests.py")
            and fn.__code__.co_name == "<lambda>"
            and "UPDATE prompt_manifests" in str(fn.__code__.co_consts)
        ):
            raise OSError("private diagnostic error")
        return await original(fn, write=write)

    try:
        monkeypatch.setattr(store, "call", fail_timing)
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM prompt_manifests").fetchone()[0]
            )
            == 1
        )
    finally:
        monkeypatch.setattr(store, "call", original)
        await runtime.close()
