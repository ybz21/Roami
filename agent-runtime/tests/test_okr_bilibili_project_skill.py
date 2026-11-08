import copy
import hashlib
import json
import runpy
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PACKAGE = Path(__file__).parents[2] / "skills/okr-development"
SCRIPTS = PACKAGE / "parts/connectors/bilibili/scripts"
single = SimpleNamespace(**runpy.run_path(str(SCRIPTS / "bilibili.py")))
with patch.dict("sys.modules", {"bilibili": single}):
    skill = SimpleNamespace(**runpy.run_path(str(SCRIPTS / "bilibili_project.py")))
store = SimpleNamespace(
    **runpy.run_path(
        str(PACKAGE / "assets/.roami/okr/skills/collection-store/scripts/collection_store.py")
    )
)
PROJECT = "fixture-project"
VIDEOS = ("BV1abcdefghj", "BV2abcdefghj")


def register(project, bvid, key, account="24"):
    value = {
        "businessKey": key,
        "platform": "bilibili",
        "accountId": account,
        "objectId": bvid,
        "url": f"https://www.bilibili.com/video/{bvid}/",
        "publishedAt": "2026-11-08T00:00:00Z",
        "mainReviewReceipt": "fixture-main-review",
        "evidenceSha256": "a" * 64,
    }
    with sqlite3.connect(store.database_path(project)) as connection:
        store.initialize(connection, PROJECT)
        store.register(connection, value)


def snapshot(bvid, owner_mid, timezone):
    data = {
        "code": 0,
        "data": {
            "bvid": bvid,
            "owner": {"mid": owner_mid},
            "aid": 42,
            "state": 0,
            "stat": {"view": 0 if bvid == VIDEOS[1] else 4, "like": 0},
        },
    }
    if bvid == VIDEOS[1]:
        del data["data"]["stat"]["like"]
    raw = json.dumps(data).encode()
    payload, values = single.parse_response(raw, bvid, owner_mid)
    return {
        "candidateOnly": True,
        "schemaVersion": 1,
        "source": {
            "service": "bilibili",
            "identity": single.source_identity(bvid, owner_mid),
            "bvid": bvid,
            "ownerMid": owner_mid,
            "aid": 42,
        },
        "capturedAt": datetime.now(UTC).isoformat(),
        "values": values,
        "evidence": {
            "payload": payload,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "http": {"status": 200, "body": raw.decode()},
        },
    }


def candidate(project):
    register(project, VIDEOS[0], "fixture-01")
    register(project, VIDEOS[1], "fixture-02")
    with patch.object(single, "collect", side_effect=snapshot):
        return skill.collect(project, PROJECT, 24, "Asia/Shanghai")


def workspace():
    return {
        "projectId": PROJECT,
        "revision": 1,
        "projectFiles": {"connectorSkillBatches": True},
        "connectors": [
            {
                "id": "bili-project",
                "service": "bilibili",
                "identity": skill.identity(PROJECT, 24),
                "window": "snapshot",
                "timezone": "Asia/Shanghai",
                "packageSha256": "b" * 64,
                "bindings": [
                    {"field": "view", "metricId": "project-views"},
                    {"field": "like", "metricId": "project-likes"},
                ],
            }
        ],
        "metrics": [
            {"id": "project-views", "source": "manual", "unit": "次"},
            {"id": "project-likes", "source": "manual", "unit": "次"},
        ],
    }


def test_registry_discovers_new_objects_without_changing_skill(tmp_path):
    register(tmp_path, VIDEOS[0], "fixture-01")
    initial = skill.publications(tmp_path, PROJECT, 24)
    assert len(initial) == 1
    register(tmp_path, VIDEOS[1], "fixture-02")
    register(tmp_path, "BV3abcdefghj", "fixture-other", account="25")
    assert len(skill.publications(tmp_path, PROJECT, 24)) == 2
    with pytest.raises(ValueError, match="another project"):
        skill.publications(tmp_path, "other-project", 24)


def test_complete_primary_evidence_and_zero_survive_batch_preparation(tmp_path):
    value = candidate(tmp_path)
    assert value["values"] == {"view": 4}
    assert value["snapshots"][1]["values"]["view"] == 0
    request, raw = skill.prepare(
        workspace(), value, "bili-project", "c" * 32, "materials/fixture/evidence.json"
    )
    assert json.loads(raw) == value
    batch = request["batch"]
    assert batch["values"] == [{"metricId": "project-views", "unit": "次", "value": 4}]
    assert batch["windowStart"] == batch["windowEnd"] == value["capturedAt"]
    assert batch["evidence"][0]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "change", ["project", "count", "body", "coverage", "boolean", "missing", "owner"]
)
def test_preparation_rejects_changed_identity_evidence_or_coverage(tmp_path, change):
    value = candidate(tmp_path)
    if change == "project":
        value["source"]["projectId"] = "another-project"
    elif change == "count":
        value["values"]["view"] += 1
    elif change == "body":
        value["snapshots"][0]["evidence"]["http"]["body"] += " "
    elif change == "coverage":
        value["coverage"][0]["publication"]["objectId"] = VIDEOS[1]
    elif change == "boolean":
        value["schemaVersion"] = True
    elif change == "missing":
        value["snapshots"].pop()
    else:
        value["source"]["ownerMid"] = 25
    with pytest.raises(ValueError):
        skill.prepare(
            workspace(), value, "bili-project", "c" * 32, "materials/fixture/evidence.json"
        )


def test_one_failed_object_cannot_publish_a_partial_project_sum(tmp_path):
    register(tmp_path, VIDEOS[0], "fixture-01")
    register(tmp_path, VIDEOS[1], "fixture-02")
    path = store.database_path(tmp_path)
    before = path.read_bytes()
    with (
        patch.object(
            single,
            "collect",
            side_effect=[
                snapshot(VIDEOS[0], 24, "Asia/Shanghai"),
                ValueError("fixture unavailable"),
            ],
        ),
        pytest.raises(ValueError, match="unavailable"),
    ):
        skill.collect(tmp_path, PROJECT, 24, "Asia/Shanghai")
    assert path.read_bytes() == before


def test_duplicate_frozen_objects_cannot_be_double_counted(tmp_path):
    value = candidate(tmp_path)
    value["coverage"][1] = copy.deepcopy(value["coverage"][0])
    value["snapshots"][1] = copy.deepcopy(value["snapshots"][0])
    value["coverageSha256"] = skill.sha256(value["coverage"])
    with pytest.raises(ValueError, match="frozen publication set"):
        skill.prepare(
            workspace(), value, "bili-project", "c" * 32, "materials/fixture/evidence.json"
        )
