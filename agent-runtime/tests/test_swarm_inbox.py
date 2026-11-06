"""Persistent questions and actual replies remain distinct from task acceptance."""

import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from test_swarm_collaboration import advance, item, plan
from test_swarm_collaboration import collaboration as collaboration_fixture
from test_swarm_project_scopes import create_project
from test_swarm_project_scopes import scoped_swarms as scoped_swarms_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.server.swarm_routes import mount_swarm_routes

collaboration = collaboration_fixture
scoped_swarms = scoped_swarms_fixture


@pytest.fixture
async def inbox_team(collaboration):
    swarms, team = collaboration
    await plan(swarms, team, [item("data"), item("publisher")])
    await advance(swarms, team)
    snapshot = await swarms.snapshot("alice", team["id"])
    actors = []
    for work in snapshot["work"]:
        actors.append(
            {
                "taskId": work["task_id"],
                "runId": work["attempt"]["runId"],
                "taskRevision": work["revision"],
            }
        )
    main = {"conversation": team["mainConversationId"]}
    return swarms, team, actors, main


async def totals(swarms):
    return await swarms.db.call(
        lambda db: {
            name: db.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0]
            for name in [
                "swarm_posts",
                "swarm_post_routes",
                "swarm_inbox",
                "swarm_commands",
                "events",
                "turns",
                "jobs",
            ]
        }
    )


@pytest.mark.parametrize("kind", ["progress", "question", "blocker", "handoff"])
async def test_only_questions_blockers_and_handoffs_enter_main_inbox(inbox_team, kind):
    swarms, team, actors, main = inbox_team
    before = await totals(swarms)
    posted = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "post", "text": "Need the actual source", "kind": kind},
        binding=actors[0],
    )
    viewed = await swarms.inbox("alice", team["id"], {})
    assert len(viewed["items"]) == (0 if kind == "progress" else 1)
    if viewed["items"]:
        entry = viewed["items"][0]
        assert entry["postId"] == posted["id"] and entry["readMs"] is None
        assert entry["taskId"] == actors[0]["taskId"] and entry["runId"] == actors[0]["runId"]
        assert entry["sourceCurrent"] is True
        read = await swarms.inbox("alice", team["id"], {}, binding=main)
        assert read["items"][0]["readMs"] is not None
        assert (await swarms.inbox("alice", team["id"], {}))["items"][0]["postId"] == posted["id"]
    after = await totals(swarms)
    assert (before["turns"], before["jobs"]) == (after["turns"], after["jobs"])


async def test_main_reply_resolves_only_its_message_and_reaches_original_member(inbox_team):
    swarms, team, actors, main = inbox_team
    question = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "q", "text": "Which source?", "kind": "question"},
        binding=actors[0],
    )
    reply = await swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "r",
            "text": "Use the confirmed source file",
            "kind": "reply",
            "replyTo": question["id"],
        },
        binding=main,
    )
    assert (await swarms.inbox("alice", team["id"], {}))["items"] == []
    received = await swarms.inbox("alice", team["id"], {}, binding=actors[0])
    assert [
        (entry["postId"], entry["author"], entry["replyTo"]) for entry in received["items"]
    ] == [(reply["id"], "main", question["id"])]
    assert (await swarms.inbox("alice", team["id"], {}, binding=actors[1]))["items"] == []
    states = [work["state"] for work in (await swarms.snapshot("alice", team["id"]))["work"]]
    assert states == ["queued", "queued"]


async def test_member_reply_does_not_accept_or_hide_the_main_review(inbox_team):
    swarms, team, actors, main = inbox_team
    view = await swarms.snapshot("alice", team["id"])
    recipient = next(
        member["id"] for member in view["members"] if member["taskId"] == actors[1]["taskId"]
    )
    question = await swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "q",
            "text": "Confirm the evidence",
            "kind": "question",
            "recipientMemberId": recipient,
        },
        binding=actors[0],
    )
    assert len((await swarms.inbox("alice", team["id"], {}, binding=actors[1]))["items"]) == 1
    await swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "r",
            "text": "Here is my observation",
            "kind": "reply",
            "replyTo": question["id"],
        },
        binding=actors[1],
    )
    assert (await swarms.inbox("alice", team["id"], {}, binding=actors[1]))["items"] == []
    assert (await swarms.inbox("alice", team["id"], {}, binding=main))["items"][0][
        "postId"
    ] == question["id"]
    assert len((await swarms.inbox("alice", team["id"], {}, binding=actors[0]))["items"]) == 1


async def test_business_key_recovers_original_message_across_tool_calls(inbox_team):
    swarms, team, actors, _ = inbox_team
    spec = {
        "commandKey": "tool-one",
        "text": "A durable question",
        "kind": "question",
        "messageKey": "source-question",
    }
    first = await swarms.post("alice", team["id"], spec, binding=actors[0])
    before = await totals(swarms)
    again = await swarms.post(
        "alice", team["id"], {**spec, "commandKey": "tool-two"}, binding=actors[0]
    )
    assert again == first
    after = await totals(swarms)
    for name in ("swarm_posts", "swarm_post_routes", "swarm_inbox", "events", "turns", "jobs"):
        assert after[name] == before[name]


@pytest.mark.parametrize(
    "change",
    [{"text": "Changed"}, {"kind": "blocker"}, {"replyTo": 999}, {"recipientMemberId": "other"}],
)
async def test_business_key_cannot_change_content_or_routing(inbox_team, change):
    swarms, team, actors, _ = inbox_team
    spec = {
        "commandKey": "first",
        "text": "Original",
        "kind": "question",
        "messageKey": "one-message",
    }
    await swarms.post("alice", team["id"], spec, binding=actors[0])
    before = await totals(swarms)
    with pytest.raises(DomainError, match="SWARM_MESSAGE_KEY_CONFLICT"):
        await swarms.post(
            "alice", team["id"], {**spec, **change, "commandKey": "new-call"}, binding=actors[0]
        )
    assert await totals(swarms) == before


async def test_different_members_can_use_the_same_local_business_key(inbox_team):
    swarms, team, actors, _ = inbox_team
    posted = [
        await swarms.post(
            "alice",
            team["id"],
            {
                "commandKey": str(index),
                "text": "My question",
                "kind": "question",
                "messageKey": "daily",
            },
            binding=actor,
        )
        for index, actor in enumerate(actors)
    ]
    assert posted[0]["id"] != posted[1]["id"]
    assert len((await swarms.inbox("alice", team["id"], {}))["items"]) == 2


@pytest.mark.parametrize("field", ["replyTo", "recipientMemberId"])
async def test_cross_project_thread_and_recipient_are_rejected(scoped_swarms, field):
    swarms = scoped_swarms
    first, second = (
        await create_project(swarms, "project-a"),
        await create_project(swarms, "project-b"),
    )
    other = await swarms.post(
        "alice", second["id"], {"commandKey": "other", "text": "Other project"}
    )
    if field == "recipientMemberId":
        await swarms.register_members(
            "alice",
            second["id"],
            {
                "commandKey": "members",
                "expectedRevision": 1,
                "members": [{"name": "Data", "executor": "codex", "duty": "Observe"}],
            },
        )
        reference = (await swarms.snapshot("alice", second["id"]))["members"][0]["id"]
    else:
        reference = other["id"]
    before = await totals(swarms)
    with pytest.raises(DomainError, match="SWARM_MESSAGE_SCOPE_CONFLICT"):
        await swarms.post(
            "alice",
            first["id"],
            {"commandKey": "bad", "text": "Must not cross", "kind": "question", field: reference},
        )
    assert await totals(swarms) == before
    with pytest.raises(DomainError, match="SWARM_NOT_FOUND"):
        await swarms.inbox("bob", first["id"], {})


async def test_inbox_failure_rolls_back_message_route_receipt_and_event(inbox_team):
    swarms, team, actors, _ = inbox_team
    await swarms.db.call(
        lambda db: db.execute(
            "CREATE TRIGGER fail_inbox BEFORE INSERT ON swarm_inbox BEGIN SELECT RAISE(ABORT,'injected'); END"
        ),
        write=True,
    )
    before = await totals(swarms)
    spec = {"commandKey": "q", "text": "Atomic question", "kind": "question"}
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        await swarms.post("alice", team["id"], spec, binding=actors[0])
    assert await totals(swarms) == before
    await swarms.db.call(lambda db: db.execute("DROP TRIGGER fail_inbox"), write=True)
    posted = await swarms.post("alice", team["id"], spec, binding=actors[0])
    assert (await swarms.inbox("alice", team["id"], {}))["items"][0]["postId"] == posted["id"]


@pytest.mark.parametrize("changed", [{"runId": "old-run"}, {"taskRevision": 9}])
async def test_stale_run_cannot_post_or_retrieve_another_round(inbox_team, changed):
    swarms, team, actors, _ = inbox_team
    stale = {**actors[0], **changed}
    before = await totals(swarms)
    with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
        await swarms.post(
            "alice",
            team["id"],
            {"commandKey": "stale", "text": "No stale question", "kind": "question"},
            binding=stale,
        )
    with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
        await swarms.inbox("alice", team["id"], {}, binding=stale)
    assert await totals(swarms) == before


async def test_private_cli_post_preserves_protocol_and_user_preview_does_not_ack(inbox_team):
    swarms, team, actors, _ = inbox_team
    app = FastAPI()
    mount_swarm_routes(app, SimpleNamespace(swarms=swarms))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fixture",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        response = await client.post(
            "/v1/swarms/" + team["id"] + "/member-posts",
            json={
                **actors[0],
                "commandKey": "cli",
                "text": "Native member question",
                "kind": "question",
                "messageKey": "native-one",
            },
        )
        assert response.status_code == 200, response.text
        post_id = response.json()["data"]["id"]
        for _ in range(2):
            preview = await client.get("/v1/swarms/" + team["id"] + "/inbox")
            assert (
                preview.status_code == 200 and preview.json()["data"]["items"][0]["readMs"] is None
            )
        snapshot = await swarms.snapshot("alice", team["id"])
        post = next(post for post in snapshot["posts"] if post["id"] == post_id)
        assert post["author"] == "data" and post["kind"] == "question"
        assert post["inbox"][0]["mainConversationId"] == team["mainConversationId"]


async def test_main_inbox_read_is_registered_with_real_bound_cli_identity(inbox_team):
    from roami_agent.tools.registry import Tools
    from roami_agent.tools.swarm_catalog import register_swarm_tools

    swarms, team, actors, main = inbox_team
    await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "q", "text": "Need Main", "kind": "question"},
        binding=actors[0],
    )
    tools = Tools()
    register_swarm_tools(tools, swarms)
    result = await tools.invoke(
        {
            "id": "read",
            "function": {
                "name": "swarm_inbox_read",
                "arguments": json.dumps({"swarmId": team["id"]}),
            },
        },
        "main",
        {"owner": "alice", **main},
    )
    assert result["items"][0]["readMs"] is not None
    assert len((await swarms.inbox("alice", team["id"], {}))["items"]) == 1


@pytest.mark.parametrize("binding", [{}, {"conversation": "another-main"}])
async def test_missing_or_wrong_main_binding_cannot_become_human(inbox_team, binding):
    swarms, team, _, _ = inbox_team
    before = await totals(swarms)
    with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
        await swarms.post(
            "alice",
            team["id"],
            {"commandKey": "bad-main", "text": "Do not impersonate", "kind": "question"},
            binding=binding,
        )
    with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
        await swarms.inbox("alice", team["id"], {}, binding=binding)
    assert await totals(swarms) == before


async def test_closed_member_cannot_append_or_mark_inbox_read(inbox_team):
    swarms, team, actors, main = inbox_team
    question = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "q", "text": "Need source", "kind": "question"},
        binding=actors[0],
    )
    await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "r", "text": "Confirmed source", "kind": "reply", "replyTo": question["id"]},
        binding=main,
    )
    await swarms.db.call(
        lambda db: db.execute(
            "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,session_id,state,updated_ms) VALUES(?,?,?,?,?,'closed',1)",
            (
                actors[0]["taskId"],
                actors[0]["taskRevision"],
                actors[0]["runId"],
                "original-launch",
                "original-session",
            ),
        ),
        write=True,
    )
    before = await totals(swarms)
    for action in ["post", "read"]:
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSED"):
            if action == "post":
                await swarms.post(
                    "alice",
                    team["id"],
                    {"commandKey": "closed", "text": "Late note"},
                    binding=actors[0],
                )
            else:
                await swarms.inbox("alice", team["id"], {}, binding=actors[0])
    assert await totals(swarms) == before


async def test_legacy_command_retry_keeps_original_receipt_after_revision_changes(inbox_team):
    swarms, team, actors, _ = inbox_team
    spec = {
        "commandKey": "original",
        "text": "One message",
        "kind": "question",
        "messageKey": "one",
    }
    first = await swarms.post("alice", team["id"], spec, binding=actors[0])
    await swarms.db.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=revision+1 WHERE id=?", (actors[0]["taskId"],)
        ),
        write=True,
    )
    before = await totals(swarms)
    assert await swarms.post("alice", team["id"], spec, binding=actors[0]) == first
    assert await totals(swarms) == before
    pending = (await swarms.inbox("alice", team["id"], {}))["items"]
    assert pending[0]["postId"] == first["id"] and pending[0]["sourceCurrent"] is False


async def test_main_cannot_create_a_self_notification(inbox_team):
    swarms, team, _, main = inbox_team
    question = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "main-question", "text": "Team discussion", "kind": "question"},
        binding=main,
    )
    await swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "main-reply",
            "text": "Additional context",
            "kind": "reply",
            "replyTo": question["id"],
        },
        binding=main,
    )
    assert (await swarms.inbox("alice", team["id"], {}, binding=main))["items"] == []


async def test_an_unrelated_post_cannot_become_a_handled_receipt(inbox_team):
    swarms, team, actors, _ = inbox_team
    question = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "q", "text": "Pending question", "kind": "question"},
        binding=actors[0],
    )
    unrelated = await swarms.post(
        "alice",
        team["id"],
        {"commandKey": "progress", "text": "Unrelated progress"},
        binding=actors[1],
    )
    with pytest.raises(sqlite3.IntegrityError, match="SWARM_RESPONSE_REQUIRED"):
        await swarms.db.call(
            lambda db: db.execute(
                "UPDATE swarm_inbox SET handled_post_id=? WHERE post_id=?",
                (unrelated["id"], question["id"]),
            ),
            write=True,
        )
    assert (await swarms.inbox("alice", team["id"], {}))["items"][0]["postId"] == question["id"]
