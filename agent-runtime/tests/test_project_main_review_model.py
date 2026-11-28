import asyncio

import httpx
from test_project_main_execution import setup_main
from test_runtime import until
from test_source_reply_review import ReviewModel

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.live_model import LiveModel
from roami_agent.replies.source_review import SourceReplyReview
from roami_agent.storage.database import row
from roami_okr.http import create_app

pytest_plugins = ["test_project_main_wakeup"]


async def test_independent_review_route_cas_keeps_project_and_native_models_separate(
    wake_runtime, monkeypatch
):
    runtime, main, launch, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], launch)
    home = await runtime.conversations.main("alice")
    default = ReviewModel([])
    default.model = "free"
    live = LiveModel(default)

    async def verdict():
        assert live.snapshot.readers == 1
        return {"accepted": True, "feedback": "Independent project review"}

    chosen = ReviewModel([verdict])
    chosen.model = "review-alt"

    def with_model(model, *, free_only):
        assert (model, free_only) == ("review-alt", False)
        return chosen

    default.with_model = with_model
    runtime.loop.reply_reviewer = SourceReplyReview(runtime.db, lambda: live)
    admissions = []

    async def gateway(_socket, model, *, allow_metered):
        admissions.append((model, allow_metered))
        if not allow_metered or model != "review-alt":
            raise DomainError("MODEL_NOT_CONFIGURED", 409)

    monkeypatch.setattr("roami_okr.main_review_model.require_gateway_model", gateway)
    route = f"/v1/conversations/{main['id']}/execution"
    update = {
        "commandKey": "save-review",
        "projectId": "project",
        "expectedGeneration": 1,
        "expectedReviewRevision": 0,
        "model": "review-alt",
        "allowMetered": True,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (
            await client.put(route + "/review-model", json=update, headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        assert not admissions
        assert (
            await client.put(route + "/review-model", json={**update, "allowMetered": False})
        ).status_code == 409
        selected = await client.put(route + "/review-model", json=update)
        assert selected.status_code == 200, selected.text
        assert (await client.put(route + "/review-model", json=update)).json() == selected.json()
        assert len(admissions) == 2
        current = (await client.get(route)).json()["data"]
        assert current["reviewRoute"] == {"revision": 1, "model": "review-alt", "freeOnly": False}
        assert current["model"] == "free" and current["sessionId"] == "native-session"
        assert (
            await client.put(
                route + "/review-model", json={**update, "commandKey": "a-stale-selection"}
            )
        ).status_code == 409
        project_turn = {"owner_id": "alice", "conversation_id": main["id"], "id": "turn"}
        project_loop = await runtime.main_executions.loop_for(runtime.loop, project_turn)
        home_turn = {**project_turn, "conversation_id": home["id"]}
        home_loop = await runtime.main_executions.loop_for(runtime.loop, home_turn)
        assert project_loop.model.model == "free" and project_loop.review_route == (
            "review-alt",
            False,
        )
        assert home_loop is runtime.loop and home_loop.review_route is None
        await runtime.start()
        turn = await runtime.chat.submit("alice", main["id"], "review-turn", "Read the team plan")
        await until(
            runtime.db,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (turn["turnId"],)
            ),
        )
        assert len(chosen.requests) == 1 and not default.requests
        if runner := runtime.turn_tasks.get(turn["turnId"]):
            await asyncio.wait_for(asyncio.shield(runner), timeout=5)
        assert live.snapshot.readers == 0
        clear = await client.put(
            route + "/review-model",
            json={
                **update,
                "commandKey": "clear-review",
                "expectedReviewRevision": 1,
                "model": None,
                "allowMetered": False,
            },
        )
        assert clear.status_code == 200
        assert (
            await runtime.main_executions.loop_for(runtime.loop, project_turn)
        ).review_route is None
