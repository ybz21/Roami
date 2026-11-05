"""Stable roles survive execution revisions without promoting reports to acceptance."""

import json

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


@pytest.fixture
async def team(store):
    runtime = Runtime(store, ConversationModel())
    runtime.swarms.chat = None
    main = await runtime.conversations.main("alice")
    origin = await runtime.conversations.accept(
        "alice", main["id"], "source", "Read reference files"
    )
    group = await runtime.swarms.create(
        "alice",
        {
            "name": "Stable team",
            "goal": "Read and verify",
            "commandKey": "team",
            "mainConversationId": main["id"],
        },
        binding={"turnId": origin["turnId"]},
    )
    try:
        yield runtime, group
    finally:
        await runtime.close()


async def register(runtime, group, *, key="roles", revision=1):
    return await runtime.swarms.register_members(
        "alice",
        group["id"],
        {
            "commandKey": key,
            "expectedRevision": revision,
            "members": [
                {"name": "research", "executor": "native", "duty": "Research and retain references"}
            ],
        },
    )


async def assigned(runtime, group):
    registered = await register(runtime, group)
    member = registered["members"][0]
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "work",
            "expectedRevision": 2,
            "items": [
                {
                    "memberId": member["id"],
                    "member": "research",
                    "executor": "native",
                    "title": "Read references",
                    "goal": "Read reference one",
                    "acceptance": "Check references",
                }
            ],
        },
    )
    await runtime.swarms.advance({"id": "advance", "aggregate_id": group["id"]})
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    return member, snapshot["work"][0]


async def finish_round(runtime, work, revision):
    task_id = work["task_id"]
    run = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
            (task_id, revision),
        )
    )
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task_id,)), write=True
    )
    await runtime.tasks.report(
        "alice",
        task_id,
        run["id"],
        revision,
        {"state": "succeeded", "summary": "Fixture reference checked", "checks": []},
    )
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=? AND json_extract(payload_json,'$.runId')=?",
            (task_id, run["id"]),
        )
    )
    await runtime.dispatch.verify(job)
    state = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task_id,))
    )
    if state["state"] == "waiting_user":
        await runtime.dispatch.confirm("alice", task_id, True, revision=revision, run_id=run["id"])
    return run


async def test_registration_has_identity_without_fabricating_a_task_or_instance(team, store):
    runtime, group = team
    created = await register(runtime, group)
    assert await register(runtime, group) == created
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    member = snapshot["members"][0]
    assert member["id"] == created["members"][0]["id"]
    assert member["state"] == "unassigned" and member["taskId"] is None
    assert not snapshot["work"] and not await runtime.tasks.list("alice")
    assert member["roundCount"] == 0 and member["id"] in member["memoryPath"]
    assert (
        await store.call(
            lambda db: db.execute("SELECT count(*) FROM native_sessions").fetchone()[0]
        )
        == 0
    )
    with pytest.raises(DomainError, match="SWARM_NOT_FOUND"):
        await runtime.swarms.member("bob", group["id"], member["id"])
    changed = {
        "commandKey": "roles",
        "expectedRevision": 1,
        "members": [{"name": "other", "executor": "native", "duty": "Other"}],
    }
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await runtime.swarms.register_members("alice", group["id"], changed)


async def test_three_rounds_keep_member_task_native_conversation_and_old_artifacts(team, store):
    runtime, group = team
    member, work = await assigned(runtime, group)
    native = await store.call(
        lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (work["task_id"],))
    )
    artifact_ids = []
    run_ids = []
    for revision in (1, 2, 3):
        run = await finish_round(runtime, work, revision)
        run_ids.append(run["id"])
        artifact = await runtime.artifacts.put(
            "alice",
            f"reference {revision}".encode(),
            task_id=work["task_id"],
            mime_type="text/plain",
            metadata={"runId": run["id"]},
        )
        artifact_ids.append(artifact["id"])
        detail = await runtime.swarms.member("alice", group["id"], member["id"])
        assert detail["member"]["roundCount"] == revision
        assert detail["rounds"]["items"][0]["state"] == "succeeded"
        if revision < 3:
            operation = await runtime.tasks.revisions.request(
                "alice",
                work["task_id"],
                f"Read reference {revision + 1}",
                revision,
                f"round-{revision + 1}",
            )
            # A queued delivery has not created a new round or completed it.
            assert (await runtime.swarms.member("alice", group["id"], member["id"]))["member"][
                "roundCount"
            ] == revision
            await runtime.tasks.revisions.advance()
            applied = await runtime.tasks.revisions.get(
                "alice", work["task_id"], operation["operationId"]
            )
            assert applied["state"] == "applied"
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    assert len(snapshot["members"]) == len(snapshot["work"]) == 1
    assert snapshot["work"][0]["memberId"] == member["id"]
    assert snapshot["work"][0]["task_id"] == work["task_id"]
    continued_native = await store.call(
        lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (work["task_id"],))
    )
    for key in (
        "id",
        "task_id",
        "conversation_id",
        "branch_id",
        "root_conversation_id",
        "parent_session_id",
    ):
        assert continued_native[key] == native[key]
    assert continued_native["last_seq"] > native["last_seq"]
    first_page = await runtime.swarms.member("alice", group["id"], member["id"], limit=2)
    second_page = await runtime.swarms.member(
        "alice", group["id"], member["id"], before=first_page["rounds"]["nextBefore"], limit=2
    )
    rounds = first_page["rounds"]["items"] + second_page["rounds"]["items"]
    assert [item["revision"] for item in rounds] == [3, 2, 1]
    assert all(item["state"] == "succeeded" for item in rounds)
    assert [item["attempts"][0]["runId"] for item in reversed(rounds)] == run_ids
    assert [item["artifacts"][0]["id"] for item in reversed(rounds)] == artifact_ids
    assert rounds[0]["request_text"] == "Read reference 3"
    assert rounds[1]["request_text"] == "Read reference 2"
    assert not second_page["rounds"]["hasMore"]


async def test_unknown_result_does_not_create_another_round_or_replace_member(team, store):
    runtime, group = team
    member, work = await assigned(runtime, group)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='failed' WHERE id=?", (work["task_id"],)),
        write=True,
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET state='unknown',result_json=? WHERE task_id=?",
            ('{"outcomeKnown":false,"inputStopped":false}', work["task_id"]),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
        await runtime.tasks.revisions.request(
            "alice", work["task_id"], "Retry the write", 1, "unsafe"
        )
    detail = await runtime.swarms.member("alice", group["id"], member["id"])
    assert detail["member"]["roundCount"] == 1
    assert detail["rounds"]["items"][0]["state"] == "unknown"
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 1


async def test_forgotten_source_is_not_reexposed_by_round_history(team, store):
    runtime, group = team
    member, _ = await assigned(runtime, group)
    source = (await runtime.swarms.member("alice", group["id"], member["id"]))["rounds"]["items"][
        0
    ]["source_message_id"]
    await store.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions VALUES(?,?,NULL,'user forget',0)", ("alice", source)
        ),
        write=True,
    )
    round_ = (await runtime.swarms.member("alice", group["id"], member["id"]))["rounds"]["items"][0]
    assert round_["request_text"] is None and round_["sourceUnavailable"]
    assert not round_["attempts"] and not round_["artifacts"]


async def test_registration_and_plan_cannot_rebind_role_executor_or_foreign_identity(team, store):
    runtime, group = team
    registered = await register(runtime, group)
    role = registered["members"][0]
    for field, value, code in [
        ("executor", "codex", "EXECUTOR"),
        ("duty", "A changed role", "DUTY"),
    ]:
        item = {
            "name": "research",
            "executor": "native",
            "duty": "Research and retain references",
            field: value,
        }
        with pytest.raises(DomainError, match=f"SWARM_MEMBER_{code}_CONFLICT"):
            await runtime.swarms.register_members(
                "alice",
                group["id"],
                {"commandKey": field, "expectedRevision": 2, "members": [item]},
            )
    with pytest.raises(DomainError, match="SWARM_MEMBER_NOT_FOUND"):
        await runtime.swarms.plan(
            "alice",
            group["id"],
            {
                "commandKey": "wrong-id",
                "expectedRevision": 2,
                "items": [
                    {
                        "memberId": "foreign",
                        "member": role["name"],
                        "executor": "native",
                        "title": "Read",
                        "goal": "Read file",
                        "acceptance": "Check references",
                    }
                ],
            },
        )
    assert not (await runtime.swarms.snapshot("alice", group["id"]))["work"]


async def test_http_and_discovered_cli_read_owned_member_rounds(team):
    runtime, group = team
    app = create_app(runtime, manage_lifecycle=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        result = await client.post(
            f"/v1/swarms/{group['id']}/members",
            json={
                "commandKey": "api",
                "expectedRevision": 1,
                "members": [{"name": "review", "executor": "codex", "duty": "Review evidence"}],
            },
        )
        assert result.status_code == 200
        member_id = result.json()["data"]["members"][0]["id"]
        assert (await client.get(f"/v1/swarms/{group['id']}/members")).json()["data"][0][
            "id"
        ] == member_id
        detail = await client.get(f"/v1/swarms/{group['id']}/members/{member_id}")
        assert detail.json()["data"]["rounds"]["items"] == []
        assert (
            await client.get(
                f"/v1/swarms/{group['id']}/members/{member_id}", headers={"X-Roami-Owner": "bob"}
            )
        ).status_code == 404
        assert (
            await client.get(f"/v1/swarms/{group['id']}/members/{member_id}?limit=0")
        ).status_code == 422
    call = {
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "argv": [
                        "roami",
                        "swarm",
                        "member",
                        "inspect",
                        "--input",
                        json.dumps({"swarmId": group["id"], "memberId": member_id}),
                    ]
                }
            ),
        }
    }
    binding = {
        "owner": "alice",
        "conversation": group["mainConversationId"],
        "turnId": "read",
        "toolCallId": "read-member",
    }
    result = await runtime.tools.invoke(call, "main", binding)
    assert result["member"]["id"] == member_id


async def test_schema19_upgrade_preserves_separate_legacy_roles_and_unknown_attempt(
    tmp_path, monkeypatch
):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks
    from roami_agent.storage import database as database_module
    from roami_agent.storage import migrations

    root = tmp_path / "legacy"
    path = root / "database/agents/runtime.db"
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 19)
        old.setattr(database_module, "SCHEMA_VERSION", 19)
        database = database_module.Database(path, root, managed=False)
        await database.open()
        try:
            conversations = Conversations(database)
            tasks = Tasks(database, conversations)

            def legacy_main(db):
                value = Conversations._new(db, "alice", "Legacy Main")
                db.execute("INSERT INTO main_conversations VALUES(?,?,1)", ("alice", value["id"]))
                return value

            main = await database.call(legacy_main, write=True)
            origin = await conversations.accept(
                "alice", main["id"], "original", "Read original references"
            )
            await database.call(
                lambda db: db.execute(
                    "INSERT INTO swarm_groups(id,owner_id,name,conversation_id,goal,target_json,created_ms,updated_ms) VALUES('legacy','alice','Legacy',?,'Read','{}',1,1)",
                    (main["id"],),
                ),
                write=True,
            )
            for name in ("research", "research-r2"):
                task = await tasks.create(
                    "alice",
                    main["id"],
                    "Read " + name,
                    key=name,
                    executor="native",
                    origin_message_id=origin["messageId"],
                )
                await database.call(
                    lambda db, name=name, task=task: db.execute(
                        "INSERT INTO swarm_work_items(id,swarm_id,member_name,executor,title,goal,acceptance,task_id) VALUES(?,'legacy',?,'native','Read','Read','Check',?)",
                        (name, name, task["id"]),
                    ),
                    write=True,
                )
            await database.call(
                lambda db: db.execute(
                    "UPDATE task_attempts SET state='unknown',result_json=? WHERE task_id=?",
                    ('{"outcomeKnown":false,"summary":"pending original callback"}', task["id"]),
                ),
                write=True,
            )
            original = await database.call(
                lambda db: [
                    dict(item) for item in db.execute("SELECT * FROM task_attempts ORDER BY id")
                ]
            )
            native = await database.call(
                lambda db: [
                    dict(item) for item in db.execute("SELECT * FROM native_sessions ORDER BY id")
                ]
            )
        finally:
            await database.close()
    database = database_module.Database(path, root, managed=False)
    await database.open()
    try:
        assert (
            await database.call(
                lambda db: [
                    dict(item) for item in db.execute("SELECT * FROM task_attempts ORDER BY id")
                ]
            )
            == original
        )
        assert (
            await database.call(
                lambda db: [
                    dict(item) for item in db.execute("SELECT * FROM native_sessions ORDER BY id")
                ]
            )
            == native
        )
        roles = await database.call(
            lambda db: [
                dict(item) for item in db.execute("SELECT * FROM swarm_members ORDER BY name")
            ]
        )
        assert [item["name"] for item in roles] == ["research", "research-r2"]
        assert all(item["id"] == item["name"] and item["legacy"] == 1 for item in roles)
        rounds = await database.call(
            lambda db: [dict(item) for item in db.execute("SELECT * FROM swarm_member_rounds")]
        )
        assert len(rounds) == 2 and all(
            item["request_text"] is None and item["legacy"] for item in rounds
        )
    finally:
        await database.close()


async def test_binding_cannot_move_a_work_item_into_another_team(team, store):
    import sqlite3

    runtime, group = team
    member, work = await assigned(runtime, group)
    other = await runtime.swarms.create(
        "alice",
        {
            "name": "Other team",
            "goal": "Separate work",
            "commandKey": "other-team",
            "mainConversationId": group["mainConversationId"],
        },
    )
    registered = await runtime.swarms.register_members(
        "alice",
        other["id"],
        {
            "commandKey": "other-role",
            "expectedRevision": 1,
            "members": [{"name": "research", "executor": "native", "duty": "Other research"}],
        },
    )
    other_member = registered["members"][0]["id"]
    with pytest.raises(sqlite3.IntegrityError, match="SWARM_MEMBER_BINDING_CONFLICT"):
        await store.call(
            lambda db: db.execute(
                "INSERT INTO swarm_member_work VALUES(?,?)", (other_member, work["id"])
            ),
            write=True,
        )
    assert (await runtime.swarms.member("alice", group["id"], member["id"]))["member"][
        "taskId"
    ] == work["task_id"]
    assert (await runtime.swarms.member("alice", other["id"], other_member))["rounds"][
        "items"
    ] == []


async def test_worker_can_read_own_rounds_but_not_other_roles_or_register_replacements(team, store):
    runtime, group = team
    member, work = await assigned(runtime, group)
    native = await store.call(
        lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (work["task_id"],))
    )
    registered = await runtime.swarms.register_members(
        "alice",
        group["id"],
        {
            "commandKey": "review-role",
            "expectedRevision": 3,
            "members": [{"name": "review", "executor": "native", "duty": "Verify outputs"}],
        },
    )
    other_member = registered["members"][0]["id"]
    binding = {
        "owner": "alice",
        "conversation": native["conversation_id"],
        "taskId": work["task_id"],
        "turnId": "worker",
        "toolCallId": "read",
    }

    def call(operation, spec):
        return {
            "function": {
                "name": "bash",
                "arguments": json.dumps(
                    {"argv": ["roami", "swarm", "member", operation, "--input", json.dumps(spec)]}
                ),
            }
        }

    own = await runtime.tools.invoke(
        call("inspect", {"swarmId": group["id"], "memberId": member["id"]}), "worker", binding
    )
    assert own["member"]["id"] == member["id"]
    with pytest.raises(DomainError, match="SWARM_MEMBER_REQUIRED"):
        await runtime.tools.invoke(
            call("inspect", {"swarmId": group["id"], "memberId": other_member}), "worker", binding
        )
    with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
        await runtime.tools.invoke(
            call(
                "register",
                {
                    "swarmId": group["id"],
                    "expectedRevision": 4,
                    "members": [
                        {"name": "replacement", "executor": "native", "duty": "Do other work"}
                    ],
                },
            ),
            "worker",
            binding,
        )
    assert len((await runtime.swarms.snapshot("alice", group["id"]))["members"]) == 2


async def test_registered_team_rejects_implicit_new_roles_in_later_plans(team):
    runtime, group = team
    await register(runtime, group)
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    assert snapshot["memberProtocol"] == 1
    with pytest.raises(DomainError, match="SWARM_MEMBER_ID_REQUIRED"):
        await runtime.swarms.plan(
            "alice",
            group["id"],
            {
                "commandKey": "replacement",
                "expectedRevision": 2,
                "items": [
                    {
                        "member": "research-r2",
                        "executor": "native",
                        "title": "Read references",
                        "goal": "Read again",
                        "acceptance": "Check references",
                    }
                ],
            },
        )
    assert len((await runtime.swarms.snapshot("alice", group["id"]))["members"]) == 1
    assert not (await runtime.swarms.snapshot("alice", group["id"]))["work"]


async def test_legacy_http_plan_receipt_replays_without_a_new_null_field(team):
    from roami_agent.server.swarm_routes import PlanSwarm

    runtime, group = team
    body = {
        "commandKey": "pre-upgrade-plan",
        "expectedRevision": 1,
        "items": [
            {
                "member": "legacy-role",
                "executor": "native",
                "title": "Read",
                "goal": "Read references",
                "acceptance": "Check references",
            }
        ],
    }
    previous_payload = PlanSwarm(**body).model_dump()
    for item in previous_payload["items"]:
        item.pop("memberId", None)
    original = await runtime.swarms.plan("alice", group["id"], previous_payload)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        replay = await client.post(f"/v1/swarms/{group['id']}/plan", json=body)
        assert replay.status_code == 200 and replay.json()["data"] == original
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    assert len(snapshot["members"]) == len(snapshot["work"]) == 1
    assert snapshot["revision"] == original["revision"]


async def test_dependency_edit_keeps_legacy_protocol(team):
    runtime, group = team

    def item(name):
        return {
            "member": name,
            "executor": "native",
            "title": name,
            "goal": "Read " + name,
            "acceptance": "Verify files",
        }

    await runtime.swarms.plan(
        "alice", group["id"], {"commandKey": "one", "expectedRevision": 1, "items": [item("first")]}
    )
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    assert snapshot["memberProtocol"] == 0
    await runtime.swarms.dependencies(
        "alice",
        group["id"],
        {
            "commandKey": "deps",
            "expectedRevision": 2,
            "workId": snapshot["work"][0]["id"],
            "dependencies": [],
        },
    )
    assert (await runtime.swarms.snapshot("alice", group["id"]))["memberProtocol"] == 0
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {"commandKey": "two", "expectedRevision": 3, "items": [item("second")]},
    )


async def test_revision_between_create_and_binding_keeps_history(team, monkeypatch):
    runtime, group = team
    registered = await register(runtime, group)
    member = registered["members"][0]
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "work",
            "expectedRevision": 2,
            "items": [
                {
                    "member": "research",
                    "memberId": member["id"],
                    "executor": "native",
                    "title": "Read",
                    "goal": "Read reference one",
                    "acceptance": "Verify",
                }
            ],
        },
    )
    create = runtime.tasks.create

    async def interleave(*args, **kwargs):
        task = await create(*args, **kwargs)
        snapshot = await runtime.swarms.snapshot("alice", group["id"])
        assert snapshot["work"][0]["task_id"] == task["id"]
        assert snapshot["members"][0]["roundCount"] == 1
        await finish_round(runtime, {"task_id": task["id"]}, 1)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Read reference two", 1, "race-round-two"
        )
        await runtime.tasks.revisions.advance()
        assert (await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"]))[
            "revision"
        ] == 2
        return task

    monkeypatch.setattr(runtime.tasks, "create", interleave)
    await runtime.swarms.advance({"id": "advance", "aggregate_id": group["id"]})
    detail = await runtime.swarms.member("alice", group["id"], member["id"])
    assert [entry["revision"] for entry in detail["rounds"]["items"]] == [2, 1]
