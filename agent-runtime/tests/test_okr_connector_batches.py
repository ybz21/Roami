import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def batch_preparer():
    script = (
        Path(__file__).parents[2]
        / "skills/okr-development/parts/connectors/github/scripts/prepare_batch.py"
    )
    spec = importlib.util.spec_from_file_location("okr_batch_preparer", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_preparation_preserves_raw_zero_and_confirmed_binding(batch_preparer):
    raw = '{ "id": 42, "full_name": "owner/repo", "private": false, "stargazers_count": 0, "forks_count": 3 }\n'
    workspace = {
        "revision": 8,
        "projectFiles": {"connectorSkillBatches": True},
        "connectors": [
            {
                "id": "github",
                "service": "github",
                "identity": "42",
                "repo": "owner/repo",
                "window": "snapshot",
                "timezone": "Asia/Shanghai",
                "packageSha256": "a" * 64,
                "bindings": [{"metricId": "stars", "field": "stars"}],
            }
        ],
        "metrics": [
            {"id": "stars", "source": "github", "repo": "owner/repo", "field": "stars", "unit": ""}
        ],
    }
    candidate = {
        "candidateOnly": True,
        "schemaVersion": 1,
        "source": {"service": "github", "repositoryId": 42, "repo": "owner/repo"},
        "capturedAt": "2026-11-02T16:30:00Z",
        "asOf": "2026-11-03",
        "values": {"stars": 0, "forks": 3},
        "evidence": {
            "sha256": batch_preparer.hashlib.sha256(raw.encode()).hexdigest(),
            "payload": json.loads(raw),
            "http": {"status": 200, "body": raw},
        },
    }
    request, evidence = batch_preparer.prepare(
        workspace, candidate, "github", "b" * 32, "delivery/raw.json"
    )
    assert evidence == raw.encode()
    assert request["revision"] == 8
    assert request["batch"]["values"] == [{"metricId": "stars", "unit": "", "value": 0}]
    assert request["batch"]["windowStart"] == candidate["capturedAt"]
    assert request["batch"]["evidence"][0]["sha256"] == candidate["evidence"]["sha256"]
    candidate["source"]["repositoryId"] = 43
    with pytest.raises(ValueError, match="source differs"):
        batch_preparer.prepare(workspace, candidate, "github", "b" * 32, "delivery/raw.json")


def test_batch_outputs_are_create_once_and_stay_in_project(batch_preparer, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = batch_preparer.destination(project, "delivery/request.json")
    batch_preparer.write_once(target, b"original request")
    batch_preparer.write_once(target, b"original request")
    with pytest.raises(ValueError, match="reconcile"):
        batch_preparer.write_once(target, b"another revision")
    assert target.read_bytes() == b"original request"
    with pytest.raises(ValueError, match="project-relative"):
        batch_preparer.destination(project, "../outside.json")
    (project / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        batch_preparer.destination(project, "link/outside.json")
