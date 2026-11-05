import asyncio

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


@pytest.fixture
async def wake_runtime(store):
    runtime = Runtime(store, ConversationModel())
    try:
        main = await runtime.conversations.create("alice", project_id="project")
        yield runtime, main
    finally:
        await runtime.close()


async def test_concurrent_daily_wakes_reuse_original_main_and_one_request(wake_runtime, store):
    runtime, main = wake_runtime
    preempted = []
    runtime.chat.preempt = preempted.append
    replies = await asyncio.gather(
        *[
            runtime.chat.wake_project(
                "alice", main["id"], "project", "daily-slot", "Continue the original team"
            )
            for _ in range(8)
        ]
    )
    assert len({reply["turnId"] for reply in replies}) == 1
    assert sum(not reply.get("reused") for reply in replies) == 1
    assert not preempted
    counts = await store.call(
        lambda db: [
            db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ["conversations", "messages", "turns", "requests", "jobs"]
        ]
    )
    assert counts == [1, 1, 1, 1, 1]
    saved = await runtime.conversations.messages("alice", main["id"])
    assert saved["messages"][0]["content"]["scheduled"] == {"projectId": "project"}
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await runtime.chat.wake_project(
            "alice", main["id"], "project", "daily-slot", "Changed text"
        )
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await runtime.chat.submit("alice", main["id"], "daily-slot", "Continue the original team")


async def test_daily_wake_does_not_preempt_a_new_user_request(wake_runtime, store):
    runtime, main = wake_runtime
    preempted = []
    runtime.chat.preempt = preempted.append
    await runtime.chat.submit("alice", main["id"], "human", "My current work")
    with pytest.raises(DomainError, match="MAIN_BUSY"):
        await runtime.chat.wake_project("alice", main["id"], "project", "daily", "Scheduled work")
    assert not preempted
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]) == 1
    )


async def test_daily_wake_preserves_an_unanswered_question_in_a_fork(wake_runtime, store):
    runtime, main = wake_runtime
    mid = await store.call(
        lambda db: message(
            db,
            main["id"],
            main["active_branch_id"],
            "assistant",
            {"question": {"prompt": "Which account?", "options": []}},
        ),
        write=True,
    )
    await runtime.conversations.fork("alice", main["id"], mid)
    with pytest.raises(DomainError, match="MAIN_WAITING_USER"):
        await runtime.chat.wake_project("alice", main["id"], "project", "daily", "Scheduled work")
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]) == 0
    )


async def test_project_wake_http_enforces_identity_owner_and_schema(wake_runtime, store):
    runtime, main = wake_runtime
    home = await runtime.conversations.main("alice")
    plain = await runtime.conversations.create("alice")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (await client.get("/v1/status")).json()["data"]["projectMainWake"] is True
        payload = {"requestKey": "daily", "projectId": "project", "text": "Continue"}
        for cid in [home["id"], plain["id"]]:
            result = await client.post(f"/v1/conversations/{cid}/wake", json=payload)
            assert result.status_code == 409, result.text
        result = await client.post(
            f"/v1/conversations/{main['id']}/wake", json={**payload, "projectId": "another"}
        )
        assert result.status_code == 409
        result = await client.post(
            f"/v1/conversations/{main['id']}/wake", json=payload, headers={"X-Roami-Owner": "bob"}
        )
        assert result.status_code == 404
        result = await client.post(
            f"/v1/conversations/{main['id']}/wake", json={**payload, "attachmentIds": []}
        )
        assert result.status_code == 422
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM requests").fetchone()[0])
            == 0
        )
        first = await client.post(f"/v1/conversations/{main['id']}/wake", json=payload)
        replay = await client.post(f"/v1/conversations/{main['id']}/wake", json=payload)
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"]["turnId"] == replay.json()["data"]["turnId"]
        assert replay.json()["data"]["reused"] is True
        branch = await store.call(
            lambda db: row(
                db, "SELECT active_branch_id FROM conversations WHERE id=?", (main["id"],)
            )
        )
        assert branch["active_branch_id"] == main["active_branch_id"]


async def test_wake_executes_on_original_main_and_replay_does_not_run_again(wake_runtime, store):
    from test_runtime import until

    runtime, main = wake_runtime
    await runtime.start()
    result = await runtime.chat.wake_project(
        "alice", main["id"], "project", "daily", "Read the existing plan"
    )
    await until(
        store,
        lambda db: (
            row(db, "SELECT state FROM turns WHERE id=?", (result["turnId"],))["state"]
            == "completed"
        ),
    )
    replay = await runtime.chat.wake_project(
        "alice", main["id"], "project", "daily", "Read the existing plan"
    )
    assert replay["turnId"] == result["turnId"] and replay["reused"] is True
    view = await runtime.conversations.messages("alice", main["id"])
    assert len(view["turns"]) == 1
    assert view["messages"][-1]["role"] == "assistant"
    assert "Read the existing plan" in view["messages"][-1]["content"]["text"]
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
        == 1
    )
