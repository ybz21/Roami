import json

import pytest
from test_publication_author_scope import artifact_fixture
from test_publication_manifest import bundle
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def prepared_command(value, tmp_path):
    runtime, binding, scope, _ = await artifact_fixture(value)
    (tmp_path / "post.txt").write_bytes(b"Frozen post")
    manifest = await runtime.artifacts.put(
        "alice",
        json.dumps(bundle(scope)).encode(),
        name="manifest.json",
        mime_type="application/json",
        task_id=scope["taskId"],
        metadata={
            "kind": "deliverable",
            "runId": scope["runId"],
            "provisional": False,
            "sourceFile": str(tmp_path / "manifest.json"),
        },
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            (json.dumps({"artifactRefs": [manifest]}), scope["runId"]),
        ),
        write=True,
    )
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT OR REPLACE INTO events(conversation_id,task_id,event_key,kind,payload_json,created_ms) VALUES(?,?,?,?,?,?)",
            (
                binding["conversation"],
                scope["taskId"],
                "workspace:" + scope["runId"],
                "task.workspace_prepared",
                json.dumps({"workspace": {"directory": str(tmp_path)}}),
                1,
            ),
        ),
        write=True,
    )
    binding["originMessageId"] = await runtime.db.call(
        lambda db: db.execute(
            "SELECT source_message_id FROM swarm_goal_delegations WHERE id=?",
            (scope["delegationId"],),
        ).fetchone()[0]
    )
    binding["toolCallId"] = "prepare-publication"
    args = {
        **scope,
        "businessKey": "first-real-post",
        "channel": "x",
        "manifest": {"id": manifest["id"], "sha256": manifest["sha256"]},
        "content": {"body": "post.txt"},
    }
    return runtime, binding, args


async def invoke(runtime, binding, args):
    return await runtime.tools.invoke(
        {
            "function": {
                "name": "bash",
                "arguments": json.dumps(
                    {
                        "argv": [
                            "roami",
                            "swarm",
                            "publication",
                            "prepare",
                            "--input",
                            json.dumps(args),
                        ]
                    }
                ),
            }
        },
        "main",
        binding,
    )


async def test_original_coordinated_main_can_freeze_via_registered_cli_without_publishing(
    coordination, tmp_path
):
    runtime, binding, args = await prepared_command(coordination, tmp_path)
    first = await invoke(runtime, binding, args)
    (tmp_path / "post.txt").write_bytes(b"Later draft")
    again = await invoke(runtime, {**binding, "toolCallId": "retry-publication"}, args)
    assert first == again and first["state"] == "frozen"
    assert first["publicationAuthorized"] is False
    assert first["artifacts"][0]["path"] == "post.txt"
    count = await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM swarm_publication_versions").fetchone()[0]
    )
    assert count == 1


@pytest.mark.parametrize("fault", ["projectId", "delegationId", "memberId", "swarmId", "runId"])
async def test_cli_cannot_freeze_another_project_goal_member_or_run(coordination, tmp_path, fault):
    runtime, binding, args = await prepared_command(coordination, tmp_path)
    args[fault] = "another"
    with pytest.raises(DomainError):
        await invoke(runtime, binding, args)
    count = await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM swarm_publication_versions").fetchone()[0]
    )
    assert count == 0
