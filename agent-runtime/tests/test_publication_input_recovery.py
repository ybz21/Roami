import json

import pytest
from test_publication_catalog import prepared_command
from test_publication_manifest import bundle
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def invoke(runtime, binding, args):
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
            "WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    return await runtime.gateway.invoke(
        turn,
        mid,
        {
            "id": identity(),
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
            },
        },
        "main",
        binding,
    )


@pytest.mark.parametrize("fault", ["flat_identity", "literal_body"])
async def test_rejected_main_input_explains_correction_without_freezing_or_duplicating(
    coordination, tmp_path, fault
):
    runtime, binding, args = await prepared_command(coordination, tmp_path)
    wrong = {**args}
    if fault == "flat_identity":
        value = bundle(args)
        value.update(value.pop("identity"))
        invalid = await runtime.artifacts.put(
            "alice",
            json.dumps(value).encode(),
            name="invalid-manifest.json",
            mime_type="application/json",
            task_id=args["taskId"],
            metadata={
                "kind": "deliverable",
                "runId": args["runId"],
                "provisional": False,
                "sourceFile": str(tmp_path / "invalid-manifest.json"),
            },
        )
        original = await runtime.artifacts.get("alice", args["manifest"]["id"])
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET result_json=? WHERE id=?",
                (json.dumps({"artifactRefs": [original, invalid]}), args["runId"]),
            ),
            write=True,
        )
        wrong["manifest"] = {"id": invalid["id"], "sha256": invalid["sha256"]}
        error, instruction = "INVALID_PUBLICATION_MANIFEST", "nested identity"
    else:
        wrong["content"] = {"body": "Frozen post"}
        error, instruction = (
            "PUBLICATION_CONTENT_USE_RELATIVE_MANIFEST_FILE_PATH",
            "exact manifest.files[].path",
        )

    rejected = await invoke(runtime, binding, wrong)
    assert rejected["error"] == error and instruction in rejected["recovery"]
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_versions").fetchone()[0]
        )
        == 0
    )
    corrected = await invoke(runtime, binding, args)
    assert corrected["state"] == "frozen" and corrected["publicationAuthorized"] is False
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_items").fetchone()[0]
        )
        == 1
    )
