import json

import pytest
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_tasks import continuing_member as continuing_member_fixture
from test_swarm_coordination_tasks import finish_main, operation, request
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.publisher_identity import publisher_identity
from roami_agent.storage.database import row

continuing_member = continuing_member_fixture
coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def running_original(value):
    runtime, team, enabled, source, _binding, _folder, _getter = value
    receipt = await request(value)
    await finish_main(value)
    await runtime.tasks.revisions.advance()
    payload = json.loads((await operation(runtime, receipt))["payload_json"])
    authorization = payload["coordinationAuthorization"]
    scope = {
        "projectId": "project-a",
        "swarmId": team["id"],
        "delegationId": enabled["delegationId"],
        "memberId": authorization["memberId"],
        "taskId": source["taskId"],
        "operationId": receipt["operationId"],
        "steerSourceRevision": 1,
        "steerSourceRunId": source["runId"],
    }
    actor = {
        "taskId": source["taskId"],
        "revision": payload["appliedRevision"],
        "runId": payload["runId"],
    }

    class WaitingExecutor:
        async def run(self, task, run):
            assert task["id"] == actor["taskId"] and run["id"] == actor["runId"]

    runtime.dispatch.executor = WaitingExecutor()
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.run' AND json_extract(payload_json,'$.runId')=?",
            (actor["runId"],),
        )
    )
    await runtime.dispatch.run(job)
    return runtime, scope, actor


async def test_actual_steer_apply_and_dispatch_preserve_original_member_identity(continuing_member):
    runtime, scope, actor = await running_original(continuing_member)
    value = await runtime.db.call(lambda db: publisher_identity(db, "alice", scope, actor))
    assert value["runId"] == actor["runId"] and value["memberId"] == scope["memberId"]


@pytest.mark.parametrize(
    "fault",
    [
        "projectId",
        "memberId",
        "operationId",
        "steerSourceRunId",
        "revision",
        "boolean_revision",
        "not_running",
        "launch",
        "cancelled",
        "revoked",
    ],
)
async def test_stale_or_unbound_execution_cannot_be_used_as_publisher(continuing_member, fault):
    runtime, scope, actor = await running_original(continuing_member)
    if fault in {"projectId", "memberId", "operationId", "steerSourceRunId"}:
        scope[fault] = "another"
    elif fault == "revision":
        actor["revision"] += 1
    elif fault == "boolean_revision":
        actor["revision"] = True
    elif fault == "not_running":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='accepted' WHERE id=?", (actor["runId"],)
            ),
            write=True,
        )
    elif fault == "launch":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET launch_id='unrelated' WHERE id=?", (actor["runId"],)
            ),
            write=True,
        )
    elif fault == "cancelled":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='cancelled' WHERE id=?", (actor["taskId"],)
            ),
            write=True,
        )
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (scope["delegationId"],),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: publisher_identity(db, "alice", scope, actor))
