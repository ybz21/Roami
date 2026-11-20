"""Only a no-send gateway receipt can defer the first model step."""

import json

import pytest
from test_local_go_gateway import gateway_fixture
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import FreeModelAdmissionDeferred
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.mark.parametrize("outcome", ["restart_and_resume", "still_blocked", "cancelled"])
async def test_free_model_wait_uses_the_durable_native_job(store, tmp_path, monkeypatch, outcome):
    socket = str(tmp_path / "model.sock")
    settings = Settings(
        endpoint="https://must-not-connect.invalid/v1",
        model="default",
        model_gateway_socket=socket,
    )
    wait_until = now_ms() + 60_000
    clock_offset = 0
    monkeypatch.setattr("roami_agent.dispatch.scheduler.now_ms", lambda: now_ms() + clock_offset)
    seen = []
    status = lambda call: 200 if call > 1 and outcome == "restart_and_resume" else 503

    def open_runtime():
        return Runtime(
            store,
            ConversationModel(),
            settings=settings,
            worker_model=configured_provider(settings, "worker"),
            memory_model=ConversationModel(),
        )

    def allow_one_model_step(db, task):
        db.execute(
            "UPDATE tasks SET budget_json=json_set(budget_json,'$.maxTurns',1) WHERE id=?",
            (task["id"],),
        )

    async with gateway_fixture(
        socket, seen, status=status, code="MODEL_ROUTE_NO_AVAILABLE_MEMBER", retry_at=wait_until
    ):
        runtime = open_runtime()
        await runtime.start()
        try:
            origin = await runtime.conversations.create("owner")
            task = await runtime.tasks.create(
                "owner",
                origin["id"],
                "Read facts",
                key="free-job",
                model="free-pool",
                free_only=True,
                record_intent=True,
                bind_task=allow_one_model_step,
            )
            runtime.wakeup.set()
            task_id = task["id"]

            def job(db):
                return row(
                    db, "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.run'", (task_id,)
                )

            def used_steps(db):
                budget = row(db, "SELECT budget_json FROM tasks WHERE id=?", (task_id,))
                return json.loads(budget["budget_json"]).get("usedSteps", 0)

            await until(store, lambda db: job(db)["available_ms"] == wait_until)
            await until(
                store,
                lambda _: (
                    not any(item["task"] == task_id for item in list(runtime.active.values()))
                ),
            )
            scheduled = await store.call(job)
            assert scheduled["state"] == "queued"
            assert scheduled["attempts"] == 1
            detail = await runtime.tasks.get("owner", task_id)
            assert detail["task"]["state"] == "queued"
            assert detail["task"]["modelRetryAtMs"] == wait_until
            assert await store.call(used_steps) == 0
            assert len(seen) == 1

            if outcome == "restart_and_resume":
                await runtime.close()
                runtime = open_runtime()
                await runtime.start()
                assert (await runtime.tasks.get("owner", task_id))["task"]["modelRetryAtMs"] == (
                    wait_until
                )
            elif outcome == "cancelled":
                await runtime.tasks.cancel("owner", task_id)

            clock_offset = wait_until - now_ms() + 10
            runtime.wakeup.set()
            expected = {
                "restart_and_resume": "succeeded",
                "still_blocked": "failed",
                "cancelled": "cancelled",
            }[outcome]
            await until(
                store,
                lambda db: (
                    row(db, "SELECT state FROM tasks WHERE id=?", (task_id,))["state"] == expected
                ),
            )
            detail = await runtime.tasks.get("owner", task_id)
            assert "modelRetryAtMs" not in detail["task"]
            assert detail["attempts"][0]["id"] == json.loads(scheduled["payload_json"])["runId"]
            assert len(detail["attempts"]) == 1
            assert len(seen) == (1 if outcome == "cancelled" else 2)
            assert all(
                body["model"] == "free-pool" and body["roami_free_only"] for _, _, body in seen
            )
            if outcome == "restart_and_resume":
                assert await store.call(used_steps) == 1

                def users(body):
                    return [
                        message["content"]
                        for message in body["messages"]
                        if message["role"] == "user"
                    ]

                original = users(seen[0][2])
                assert any("Read facts" in content for content in original)
                assert users(seen[-1][2]) == original
        finally:
            await runtime.close()


@pytest.mark.parametrize("prior_evidence", ["tool_call", "resource_action"])
async def test_free_model_block_after_progress_is_not_requeued(store, prior_evidence):
    def record_resource_action(db):
        run = row(db, "SELECT * FROM task_attempts WHERE state='running'")
        db.execute(
            "INSERT INTO resources(id,node_id,kind,resource_key) VALUES('recorded','local','browser','fixture')"
        )
        db.execute(
            "INSERT INTO resource_observations(id,resource_id,task_id,run_id,lease_epoch,scene_epoch,signature,body_json,captured_ms) "
            "VALUES('observed','recorded',?,?,0,0,'fixture','{}',0)",
            (run["task_id"], run["id"]),
        )
        db.execute(
            "INSERT INTO resource_actions(id,resource_id,task_id,run_id,lease_epoch,observation_id,idempotency_key,payload_sha256,action_json,state,created_ms,updated_ms) "
            "VALUES('write','recorded',?,?,0,'observed','fixture','fixture','{}','unknown',0,0)",
            (run["task_id"], run["id"]),
        )

    class Worker(ConversationModel):
        calls = 0

        def with_model(self, model, *, free_only=False):
            return self

        async def stream(self, messages, tools):
            self.calls += 1
            if prior_evidence == "resource_action":
                await store.call(record_resource_action, write=True)
                raise FreeModelAdmissionDeferred(now_ms() + 60_000)
            if self.calls > 1:
                raise FreeModelAdmissionDeferred(now_ms() + 60_000)
            yield ModelEvent(
                "tool",
                {
                    "id": "first-action",
                    "type": "function",
                    "function": {"name": "tool_list", "arguments": "{}"},
                },
            )

    worker = Worker()
    runtime = Runtime(store, ConversationModel(), worker_model=worker)
    await runtime.start()
    try:
        origin = await runtime.conversations.create("owner")
        task = await runtime.tasks.create(
            "owner", origin["id"], "Read facts", key="free-job", free_only=True, record_intent=True
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(db, "SELECT id FROM tasks WHERE id=? AND state='failed'", (task["id"],)),
        )
        detail = await runtime.tasks.get("owner", task["id"])
        assert "modelRetryAtMs" not in detail["task"]
        assert worker.calls == (1 if prior_evidence == "resource_action" else 2)
        assert (
            await store.call(
                lambda db: row(
                    db,
                    "SELECT COUNT(*) AS n FROM events WHERE task_id=? AND kind='task.waiting_for_free_model'",
                    (task["id"],),
                )["n"]
            )
            == 0
        )
    finally:
        await runtime.close()
