"""A prepared provider replaces the executor generation, never the member or old task."""

import copy
import json
from types import SimpleNamespace

import pytest
from test_swarm_execution_migration import pause

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_okr.main import open_main
from roami_okr.main_execution import main_configuration

pytest_plugins = ["test_swarm_delegations"]


def prepared(key, *, session="session-claude", model="free", directory="/project"):
    return {
        "ready": True,
        "launchKey": key,
        "sessionId": session,
        "executor": "claude",
        "configuredModel": model,
        "sessionBinding": {
            "id": session,
            "name": session,
            "tmuxId": "$one",
            "pane": "%one",
            "created": "123",
            "providerConversationId": "provider-claude",
            "hostProof": "host",
            "directoryProof": "directory",
            "directory": directory,
        },
        "workspace": {"directory": directory},
    }


async def setup_generation(fixture, monkeypatch, *, proof=None):
    runtime, _, group, *_ = fixture
    runtime.swarms.settings = SimpleNamespace(cli_bin="unused")
    member = (await runtime.swarms.snapshot("alice", group["id"], include_memory=False))["members"][
        0
    ]
    await pause(runtime, group, 2)
    spec = {
        "commandKey": "replace-provider",
        "expectedRevision": 3,
        "members": [
            {
                "memberId": member["id"],
                "executor": "claude",
                "model": "free",
                "preparedLaunchKey": "prepared-role",
            }
        ],
    }
    calls = []

    async def workspace(self, project):
        assert project == "project-a"
        return {"projectId": project, "directory": "/project"}

    async def command(self, sub, *args, **kwargs):
        calls.append((sub, args))
        assert sub == "prepared" and args == ("--key", "prepared-role")
        return copy.deepcopy(proof or prepared("prepared-role"))

    monkeypatch.setattr(TargetDirectory, "project_workspace", workspace)
    monkeypatch.setattr(CodingExecutor, "command", command)
    return runtime, group, member, spec, calls


async def test_provider_replacement_retains_role_and_paused_state(delegated_team, monkeypatch):
    runtime, group, member, spec, calls = await setup_generation(delegated_team, monkeypatch)
    before = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (member["id"],))
    )
    receipt = await runtime.swarms.migrate_execution("alice", group["id"], spec)
    assert (
        receipt["paused"] is True and receipt["members"][0]["providerSessionId"] == "session-claude"
    )
    assert await runtime.swarms.migrate_execution("alice", group["id"], spec) == receipt
    assert len(calls) == 1
    after = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (member["id"],))
    )
    assert (after["id"], after["name"], after["duty"]) == (
        before["id"],
        before["name"],
        before["duty"],
    )
    assert (
        after["executor"] == "claude"
        and after["model"] == "free"
        and after["execution_generation"] == 2
    )
    snapshot = await runtime.swarms.snapshot("alice", group["id"], include_memory=False)
    provider = next(m for m in snapshot["members"] if m["id"] == member["id"])["provider"]
    assert provider["sessionId"] == "session-claude" and provider["model"] == "free"
    assert (await runtime.db.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 0
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT count(*) AS n FROM swarm_member_provider_generations")
        )
    )["n"] == 1


@pytest.mark.parametrize("change", ["model", "directory", "provider", "ready", "binding", "key"])
async def test_preparation_mismatch_never_changes_member(delegated_team, monkeypatch, change):
    proof = prepared("prepared-role")
    if change == "model":
        proof["configuredModel"] = "paid"
    if change == "directory":
        proof["workspace"]["directory"] = "/other-project"
    if change == "provider":
        proof["sessionBinding"]["providerConversationId"] = ""
    if change == "ready":
        proof["ready"] = False
    if change == "binding":
        proof["sessionBinding"]["id"] = "other-session"
    if change == "key":
        proof["launchKey"] = "other-key"
    runtime, group, member, spec, _ = await setup_generation(
        delegated_team, monkeypatch, proof=proof
    )
    with pytest.raises(DomainError, match="SWARM_PREPARATION_UNCONFIRMED"):
        await runtime.swarms.migrate_execution("alice", group["id"], spec)
    value = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (member["id"],))
    )
    assert value["executor"] == "codex" and value["execution_generation"] == 1
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT count(*) AS n FROM swarm_member_provider_generations")
        )
    )["n"] == 0


async def test_prepared_generation_reuses_the_same_session_on_assignment(
    delegated_team, monkeypatch
):
    runtime, group, member, spec, _ = await setup_generation(delegated_team, monkeypatch)
    await runtime.swarms.migrate_execution("alice", group["id"], spec)
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "next-work",
            "expectedRevision": 4,
            "items": [
                {
                    "memberId": member["id"],
                    "member": member["name"],
                    "executor": "claude",
                    "title": "Read references",
                    "goal": "Read existing project references",
                    "acceptance": "Report actual evidence",
                }
            ],
        },
    )

    async def memory(*args):
        return {"content": "Retained team knowledge"}

    monkeypatch.setattr(runtime.swarms, "memory_read", memory)
    await runtime.swarms.control(
        "alice",
        group["id"],
        {"commandKey": "resume-fixture", "expectedRevision": 5, "action": "resume"},
    )
    await runtime.swarms.advance({"id": "assignment-fixture", "aggregate_id": group["id"]})
    task = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks"))
    assert task is not None
    assert json.loads(task["intent_json"])["executor"] == "claude"
    target = json.loads(task["intent_json"])["target"]
    assert target["kind"] == "session" and target["sessionId"] == "session-claude"
    assert target["providerLaunchKey"] == "prepared-role"
    await runtime.swarms.advance({"id": "repeat-fixture", "aggregate_id": group["id"]})
    assert (await runtime.db.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 1


async def test_revision_changed_during_provider_check_aborts_binding(delegated_team, monkeypatch):
    runtime, group, member, spec, _ = await setup_generation(delegated_team, monkeypatch)

    async def command(self, sub, *args, **kwargs):
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (group["id"],)
            ),
            write=True,
        )
        return prepared("prepared-role")

    monkeypatch.setattr(CodingExecutor, "command", command)
    with pytest.raises(DomainError, match="SWARM_PLAN_CHANGED"):
        await runtime.swarms.migrate_execution("alice", group["id"], spec)
    current = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (member["id"],))
    )
    assert current["executor"] == "codex" and current["execution_generation"] == 1
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT count(*) AS n FROM swarm_member_provider_generations")
        )
    )["n"] == 0


async def test_provider_context_cannot_be_shared_by_different_members(delegated_team, monkeypatch):
    runtime, group, member, spec, _ = await setup_generation(delegated_team, monkeypatch)
    await runtime.swarms.migrate_execution("alice", group["id"], spec)
    members = (await runtime.swarms.snapshot("alice", group["id"], include_memory=False))["members"]
    other = next(m for m in members if m["id"] != member["id"])
    next_spec = {
        "commandKey": "different-member",
        "expectedRevision": 4,
        "members": [
            {
                "memberId": other["id"],
                "executor": "claude",
                "model": "free",
                "preparedLaunchKey": "another-preparation",
            }
        ],
    }

    async def command(self, sub, *args, **kwargs):
        return prepared("another-preparation", session="another-session")

    monkeypatch.setattr(CodingExecutor, "command", command)
    with pytest.raises(DomainError, match="SWARM_PROVIDER_ALREADY_BOUND"):
        await runtime.swarms.migrate_execution("alice", group["id"], next_spec)
    current = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (other["id"],))
    )
    assert current["executor"] == "codex" and current["execution_generation"] == 1
    snapshot = await runtime.swarms.snapshot("alice", group["id"], include_memory=False)
    assert snapshot["revision"] == 4 and snapshot["paused"] is True


@pytest.mark.parametrize("first", ["project-main", "member"])
@pytest.mark.parametrize("conflict", ["session", "provider"])
async def test_prepared_binding_cannot_cross_main_and_member(
    delegated_team, monkeypatch, first, conflict
):
    runtime, group, member, member_spec, _ = await setup_generation(delegated_team, monkeypatch)
    main = await open_main(runtime.conversations, "bob", "other-project")
    main_spec = {
        "commandKey": "bind-project-main",
        "projectId": "other-project",
        "expectedGeneration": 0,
        "executor": "claude",
        "model": "free",
        "preparedLaunchKey": "prepared-project-main",
    }
    proof = prepared(
        "prepared-project-main",
        session="session-claude" if conflict == "session" else "main-session",
    )
    if conflict == "session":
        proof["sessionBinding"]["providerConversationId"] = "main-provider"

    async def workspace(self, project):
        assert project in ("project-a", "other-project")
        return {"projectId": project, "directory": "/project"}

    async def prepare_main(command, *args, **kwargs):
        assert (command, args) == ("prepared", ("--key", "prepared-project-main"))
        return proof

    monkeypatch.setattr(TargetDirectory, "project_workspace", workspace)
    runtime.main_executions.executor = SimpleNamespace(command=prepare_main)

    async def bind_main():
        return await runtime.main_executions.configure("bob", main["id"], main_spec)

    async def bind_member():
        return await runtime.swarms.migrate_execution("alice", group["id"], member_spec)

    accepted, rejected = (
        (bind_main, bind_member) if first == "project-main" else (bind_member, bind_main)
    )
    receipt = await accepted()
    with pytest.raises(DomainError, match="SWARM_PROVIDER_ALREADY_BOUND"):
        await rejected()
    assert await accepted() == receipt
    team = await runtime.swarms.snapshot("alice", group["id"], include_memory=False)
    current = next(value for value in team["members"] if value["id"] == member["id"])
    assert (team["revision"], current["executor"]) == (
        (3, "codex") if first == "project-main" else (4, "claude")
    )
    stored = await runtime.db.call(lambda db: main_configuration(db, "bob", main["id"]))
    assert stored["generation"] == (1 if first == "project-main" else 0)


async def test_http_migration_accepts_only_host_verified_preparation(delegated_team, monkeypatch):
    import httpx

    from roami_agent.server.http import create_app

    runtime, group, _, spec, calls = await setup_generation(delegated_team, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        path = f"/v1/swarms/{group['id']}/execution-migrations"
        foreign = await client.post(path, headers={"X-Roami-Owner": "bob"}, json=spec)
        assert foreign.status_code == 404 and calls == []
        forged = copy.deepcopy(spec)
        forged["members"][0]["proof"] = prepared("prepared-role")
        rejected = await client.post(path, json=forged)
        assert rejected.status_code == 422 and calls == []
        accepted = await client.post(path, json=spec)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["members"][0]["providerSessionId"] == "session-claude"
        replay = await client.post(path, json=spec)
        assert replay.json() == accepted.json() and len(calls) == 1
