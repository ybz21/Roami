import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def test_identity_distinguishes_home_and_a_fixed_project_main_without_a_team(store):
    runtime = Runtime(store, ConversationModel())
    try:
        home = await runtime.conversations.main("alice")
        project = await runtime.conversations.create("alice", project_id="project")
        before = await store.call(
            lambda db: db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        )
        assert (await runtime.conversations.identity("alice", home["id"]))["kind"] == "home_main"
        value = await runtime.conversations.identity("alice", project["id"])
        assert value == {
            "conversationId": project["id"],
            "activeBranchId": project["active_branch_id"],
            "kind": "project_main",
            "projectId": "project",
        }
        assert await runtime.conversations.identity("alice", project["id"]) == value
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            )
            == before
        )
        assert not (await runtime.swarms.list("alice"))
        with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
            await runtime.conversations.identity("bob", project["id"])
    finally:
        await runtime.close()


async def test_identity_never_promotes_a_worker_into_a_main(store):
    runtime = Runtime(store, ConversationModel())
    try:
        project = await runtime.conversations.create("alice", project_id="project")
        task = await runtime.tasks.create(
            "alice",
            project["id"],
            "Read project files",
            key="member",
            executor="native",
            record_intent=True,
        )
        native = await store.call(
            lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (task["id"],))
        )
        value = await runtime.conversations.identity("alice", native["conversation_id"])
        assert (
            value["kind"] == "member"
            and value["taskId"] == task["id"]
            and value["nativeSessionId"] == native["id"]
        )
        assert "projectId" not in value
    finally:
        await runtime.close()


@pytest.mark.parametrize("corruption", ["home", "project_binding", "shared_team"])
async def test_identity_fails_closed_on_conflicting_main_bindings(store, corruption):
    runtime = Runtime(store, ConversationModel())
    try:
        project = await runtime.conversations.create("alice", project_id="project")
        if corruption == "home":
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO main_conversations VALUES(?,?,0)", ("alice", project["id"])
                ),
                write=True,
            )
        elif corruption == "project_binding":
            await store.call(
                lambda db: db.execute(
                    "UPDATE project_okr_conversations SET project_id='other' WHERE conversation_id=?",
                    (project["id"],),
                ),
                write=True,
            )
        else:
            runtime.swarms.chat = None
            group = await runtime.swarms.create(
                "alice",
                {
                    "name": "Team",
                    "goal": "Original project",
                    "target": {"kind": "project", "projectId": "project"},
                    "mainConversationId": project["id"],
                    "commandKey": "create",
                },
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE swarm_groups SET target_json=? WHERE id=?",
                    ('{"kind":"project","projectId":"other"}', group["id"]),
                ),
                write=True,
            )
        with pytest.raises(DomainError, match="CONVERSATION_IDENTITY_CONFLICT"):
            await runtime.conversations.identity("alice", project["id"])
    finally:
        await runtime.close()


async def test_http_identity_is_owned_and_advertised_without_creating_a_conversation(store):
    runtime = Runtime(store, ConversationModel())
    project = await runtime.conversations.create("alice", project_id="project")
    app = create_app(runtime, manage_lifecycle=False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            assert (await client.get("/v1/status")).json()["data"]["conversationIdentity"] is True
            response = await client.get(f"/v1/conversations/{project['id']}/identity")
            assert response.status_code == 200 and response.json()["data"]["projectId"] == "project"
            assert (
                await client.get(
                    f"/v1/conversations/{project['id']}/identity", headers={"X-Roami-Owner": "bob"}
                )
            ).status_code == 404
    finally:
        await runtime.close()
