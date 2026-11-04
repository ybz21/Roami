import json

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.conversation.project_okr import registered_project
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tool_arguments import ToolArgumentsError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


@pytest.fixture
async def project_runtime(store, monkeypatch):
    calls = []
    state = {"workspace": None}

    async def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["project", "show"]:
            data = {"key": argv[3]}
        elif argv[3] == "show":
            data = state["workspace"]
        else:
            body = json.loads(kwargs["input_data"])
            if body["revision"] != (state["workspace"] or {}).get("revision", 0):
                return {"exitCode": 1, "stdout": '{"error":"OKR_CONFLICT"}'}
            data = {**body, "revision": body["revision"] + 1, "projectId": argv[4]}
            state["workspace"] = data
        return {"exitCode": 0, "stdout": json.dumps({"data": data})}

    monkeypatch.setattr("roami_agent.conversation.project_okr.execute", execute)
    runtime = Runtime(store, ConversationModel())
    try:
        yield runtime, calls, state
    finally:
        await runtime.close()


async def create_goal(runtime, project="registered", key="goal"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        return await client.post(
            "/v1/conversations",
            json={"projectId": project, "title": "Goal discussion", "requestKey": key},
        )


async def test_goal_discussion_binds_registered_project_independently_and_idempotently(
    project_runtime, store
):
    runtime, calls, _ = project_runtime
    result = await create_goal(runtime)
    assert result.status_code == 201, result.text
    cid = result.json()["data"]["id"]
    assert cid != (await runtime.conversations.main("alice"))["id"]
    binding = await store.call(
        lambda db: row(
            db, "SELECT * FROM project_okr_conversations WHERE conversation_id=?", (cid,)
        )
    )
    assert binding["project_id"] == "registered" and binding["owner_id"] == "alice"
    assert (await create_goal(runtime)).json()["data"]["id"] == cid
    assert (await create_goal(runtime, project="another-project")).status_code == 409
    assert calls[0][0] == ["roami", "project", "show", "registered", "--json"]


async def test_bound_goal_tools_read_empty_goal_and_save_only_its_project(project_runtime):
    runtime, calls, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    binding = {"owner": "alice", "conversation": cid, "role": "main"}
    read = runtime.tools.registry["project_okr_context"]
    update = runtime.tools.registry["project_okr_update"]
    assert await read.handler({}, binding) == {"projectId": "registered", "saved": False}
    body = {"revision": 0, "objective": "User confirmed", "keyResults": []}
    saved = await update.handler({"operation": "save", "payload": body}, binding)
    assert saved["revision"] == 1 and saved["projectId"] == "registered"
    assert calls[-1][0] == [
        "roami",
        "project",
        "okr",
        "save",
        "registered",
        "--file",
        "-",
        "--json",
    ]
    assert json.loads(calls[-1][1]["input_data"]) == body
    assert (await read.handler({}, binding))["objective"] == "User confirmed"
    with pytest.raises(DomainError, match="OKR_CONFLICT"):
        await update.handler({"operation": "save", "payload": body}, binding)
    with pytest.raises(ToolArgumentsError):
        update.validate({"operation": "save", "payload": body, "projectId": "another"})


async def test_goal_tools_reject_home_workers_and_other_owners_before_execution(project_runtime):
    runtime, calls, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    home = (await runtime.conversations.main("alice"))["id"]
    read = runtime.tools.registry["project_okr_context"]
    count = len(calls)
    for binding in [
        {"owner": "alice", "conversation": home},
        {"owner": "alice", "conversation": cid, "taskId": "worker"},
        {"owner": "bob", "conversation": cid},
    ]:
        with pytest.raises(DomainError):
            await read.handler({}, binding)
    assert len(calls) == count


@pytest.mark.parametrize("pid", ["--server=https://unrelated", "", "bad\0project"])
async def test_goal_binding_rejects_option_like_project_ids_before_cli(project_runtime, pid):
    runtime, calls, _ = project_runtime
    with pytest.raises(DomainError, match="INVALID_OKR_PROJECT_ID"):
        await registered_project(runtime.settings, pid)
    assert not calls
