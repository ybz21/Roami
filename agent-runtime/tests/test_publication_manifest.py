import asyncio
import hashlib
import json

import pytest
from test_publication_author_scope import artifact_fixture
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_manifest import PublicationManifest, selected_files
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_author_scope import candidate_artifacts

coordination = coordination_fixture
delegated_team = delegated_team_fixture


def bundle(scope, body=b"Frozen post"):
    return {
        "identity": {k: scope[k] for k in ("taskId", "revision", "runId")},
        "files": [
            {
                "path": "post.txt",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                **{k: scope[k] for k in ("taskId", "revision", "runId")},
            }
        ],
    }


@pytest.mark.parametrize("fault", ["path", "run", "size", "hash", "duplicate", "selection"])
def test_invalid_or_cross_run_manifest_is_rejected(fault):
    scope = {"taskId": "task", "revision": 4, "runId": "run"}
    value = bundle(scope)
    paths = ["post.txt"]
    if fault == "path":
        value["files"][0]["path"] = "../post.txt"
        paths = ["../post.txt"]
    elif fault == "run":
        value["files"][0]["runId"] = "old"
    elif fault == "size":
        value["files"][0]["bytes"] = True
    elif fault == "hash":
        value["files"][0]["sha256"] = "author-claim"
    elif fault == "duplicate":
        value["files"] *= 2
    else:
        paths *= 2
    with pytest.raises(DomainError):
        selected_files(json.dumps(value), scope, paths)


@pytest.mark.parametrize("fault", [None, "changed", "symlink", "parent_symlink", "stale_run"])
async def test_snapshot_uses_retained_current_manifest_and_exact_source_bytes(
    coordination, tmp_path, fault
):
    runtime, binding, scope, _ = await artifact_fixture(coordination)
    root = tmp_path / "run"
    root.mkdir()
    path = root / "post.txt"
    path.write_bytes(b"Frozen post")
    manifest = bundle(scope)
    retained = await runtime.artifacts.put(
        "alice",
        json.dumps(manifest).encode(),
        task_id=scope["taskId"],
        name="manifest.json",
        mime_type="application/json",
        metadata={
            "kind": "deliverable",
            "runId": scope["runId"],
            "provisional": False,
            "sourceFile": str(root / "manifest.json"),
        },
    )

    def register(db):
        db.execute(
            "INSERT OR REPLACE INTO events(conversation_id,task_id,event_key,kind,payload_json,created_ms) VALUES(?,?,?,?,?,?)",
            (
                binding["conversation"],
                scope["taskId"],
                "workspace:" + scope["runId"],
                "task.workspace_prepared",
                json.dumps({"workspace": {"directory": str(tmp_path)}}),
                1,
            ),
        )
        db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            (json.dumps({"artifactRefs": [retained]}), scope["runId"]),
        )

    await runtime.db.call(register, write=True)
    if fault == "changed":
        path.write_bytes(b"Wrong bytes")
    elif fault == "symlink":
        path.unlink()
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"Frozen post")
        path.symlink_to(outside)
    elif fault == "parent_symlink":
        original = tmp_path / "original"
        root.rename(original)
        root.symlink_to(original, target_is_directory=True)
    elif fault == "stale_run":
        scope["runId"] = "old"
    importer = PublicationManifest(runtime.db, runtime.artifacts)
    if fault:
        with pytest.raises(DomainError):
            await importer.snapshot(binding, scope, retained, ["post.txt"])
    else:
        result, concurrent = await asyncio.gather(
            importer.snapshot(binding, scope, retained, ["post.txt"]),
            importer.snapshot(binding, scope, retained, ["post.txt"]),
        )
        assert result == concurrent
        assert result["publicationAuthorized"] is False
        imported = result["artifacts"][0]
        _, body = await runtime.artifacts.read("alice", imported["id"])
        assert body == b"Frozen post"
        proof = await runtime.db.call(
            lambda db: candidate_artifacts(db, binding, scope, [imported])
        )
        assert proof[0]["sha256"] == hashlib.sha256(body).hexdigest()
        path.write_bytes(b"Later edit")
        _, frozen = await runtime.artifacts.read("alice", imported["id"])
        assert frozen == b"Frozen post"
