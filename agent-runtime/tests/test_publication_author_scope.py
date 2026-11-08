import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.publication_author_scope import candidate_artifacts, candidate_author

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def scope_fixture(value):
    runtime, _, team, enabled, post, actor = value
    await post()
    artifact = await runtime.artifacts.put(
        "alice",
        b"Exact current post",
        name="post.md",
        mime_type="text/markdown",
        task_id=actor["taskId"],
        metadata={"kind": "deliverable", "runId": actor["runId"], "provisional": False},
    )
    await runtime.tasks.report(
        "alice",
        actor["taskId"],
        actor["runId"],
        1,
        {
            "state": "succeeded",
            "summary": "Candidate ready",
            "artifactRefs": [artifact],
            "inputStopped": True,
            "outcomeKnown": True,
        },
    )

    async def verified(task, result):
        return True

    runtime.dispatch.verifier = verified
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (actor["taskId"],)
        )
    )
    await runtime.dispatch.verify(job)
    turn = await claim(runtime, await queue(runtime, team))
    mid = await runtime.journal.start(turn)
    binding = {
        "owner": "alice",
        "role": "main",
        "conversation": team["mainConversationId"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "assistantMessageId": mid,
    }
    member = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT m.id FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id WHERE w.task_id=?",
            (actor["taskId"],),
        )
    )
    scope = {
        "projectId": "project-a",
        "swarmId": team["id"],
        "delegationId": enabled["delegationId"],
        "memberId": member["id"],
        "taskId": actor["taskId"],
        "revision": 1,
        "runId": actor["runId"],
    }
    return runtime, binding, scope


async def test_current_original_member_candidate_has_scoped_authorship(coordination):
    runtime, binding, scope = await scope_fixture(coordination)
    proof = await runtime.db.call(lambda db: candidate_author(db, binding, scope))
    assert (
        proof["runId"] == scope["runId"] and proof["mainConversationId"] == binding["conversation"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "project",
        "member",
        "task",
        "revision",
        "run",
        "failed",
        "paused",
        "revoked",
        "worker",
        "home",
    ],
)
async def test_other_team_or_stale_author_cannot_be_frozen(coordination, fault):
    runtime, binding, scope = await scope_fixture(coordination)
    if fault in {"project", "member", "task", "run"}:
        scope[
            {"project": "projectId", "member": "memberId", "task": "taskId", "run": "runId"}[fault]
        ] = "other"
    elif fault == "revision":
        scope["revision"] += 1
    elif fault == "worker":
        binding["role"] = "worker"
    elif fault == "home":
        binding["conversation"] = (await runtime.conversations.create("alice"))["id"]
    elif fault == "failed":
        await runtime.db.call(
            lambda db: db.execute("UPDATE tasks SET state='failed' WHERE id=?", (scope["taskId"],)),
            write=True,
        )
    elif fault == "paused":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_groups SET paused=1 WHERE id=?", (scope["swarmId"],)
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
        await runtime.db.call(lambda db: candidate_author(db, binding, scope))


async def artifact_fixture(value):
    runtime, binding, scope = await scope_fixture(value)
    artifact = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id,sha256 FROM artifacts WHERE task_id=? AND name='post.md'",
            (scope["taskId"],),
        )
    )
    return runtime, binding, scope, [artifact]


async def test_current_run_report_and_host_artifact_index_both_match(coordination):
    runtime, binding, scope, required = await artifact_fixture(coordination)
    proof = await runtime.db.call(lambda db: candidate_artifacts(db, binding, scope, required))
    assert proof[0]["id"] == required[0]["id"] and proof[0]["sizeBytes"] == len(
        b"Exact current post"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "sha",
        "old_run",
        "other_task",
        "unreported",
        "provisional",
        "deleted",
        "purged",
        "duplicate",
        "empty",
    ],
)
async def test_old_or_unreported_artifact_cannot_enter_frozen_candidate(coordination, fault):
    runtime, binding, scope, required = await artifact_fixture(coordination)
    aid = required[0]["id"]
    if fault == "sha":
        required[0]["sha256"] = "0" * 64
    elif fault == "duplicate":
        required *= 2
    elif fault == "empty":
        required = []
    elif fault == "unreported":
        other = await runtime.artifacts.put(
            "alice",
            b"Not in actual result",
            name="new.md",
            mime_type="text/markdown",
            task_id=scope["taskId"],
            metadata={"kind": "deliverable", "runId": scope["runId"]},
        )
        required = [{"id": other["id"], "sha256": other["sha256"]}]
    elif fault == "old_run":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE artifacts SET metadata_json=json_set(metadata_json,'$.runId','previous') WHERE id=?",
                (aid,),
            ),
            write=True,
        )
    elif fault == "provisional":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE artifacts SET metadata_json=json_set(metadata_json,'$.provisional',json('true')) WHERE id=?",
                (aid,),
            ),
            write=True,
        )
    elif fault == "other_task":
        await runtime.db.call(
            lambda db: db.execute("UPDATE artifacts SET task_id=NULL WHERE id=?", (aid,)),
            write=True,
        )
    else:
        column = "deleted_ms" if fault == "deleted" else "purged_ms"
        await runtime.db.call(
            lambda db: db.execute("UPDATE artifacts SET " + column + "=1 WHERE id=?", (aid,)),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: candidate_artifacts(db, binding, scope, required))


@pytest.mark.parametrize("fault", [None, "unreported", "other_run", "unknown", "provisional"])
async def test_cli_retained_output_needs_current_host_workspace_and_report(coordination, fault):
    import json

    runtime, binding, scope, required = await artifact_fixture(coordination)
    path = "/workspace/review.md"
    result = {
        "executor": "roami-cli",
        "state": "succeeded",
        "inputStopped": True,
        "outcomeKnown": fault != "unknown",
        "summary": "[review](" + path + ")",
    }
    metadata = {
        "kind": "deliverable",
        "provisional": fault == "provisional",
        "runId": "old" if fault == "other_run" else scope["runId"],
        "sourceFile": "/workspace/unreported.md" if fault == "unreported" else path,
    }

    def prepare(db):
        db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            (json.dumps(result), scope["runId"]),
        )
        db.execute(
            "UPDATE artifacts SET metadata_json=? WHERE id=?",
            (json.dumps(metadata), required[0]["id"]),
        )
        db.execute(
            "INSERT OR REPLACE INTO events(conversation_id,task_id,event_key,kind,payload_json,created_ms) VALUES(?,?,?,?,?,?)",
            (
                binding["conversation"],
                scope["taskId"],
                "workspace:" + scope["runId"],
                "task.workspace_prepared",
                json.dumps({"workspace": {"directory": "/workspace"}}),
                1,
            ),
        )

    await runtime.db.call(prepare, write=True)
    if fault:
        with pytest.raises(DomainError):
            await runtime.db.call(lambda db: candidate_artifacts(db, binding, scope, required))
    else:
        proof = await runtime.db.call(lambda db: candidate_artifacts(db, binding, scope, required))
        assert proof[0]["id"] == required[0]["id"]
