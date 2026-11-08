"""Collect confirmed project publications; prepare a candidate, never publish it."""

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import bilibili


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def identity(project_id, owner_mid):
    if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project_id):
        raise ValueError("Expected the confirmed project ID")
    if type(owner_mid) is not int or not 0 < owner_mid <= bilibili.MAX_COUNT:
        raise ValueError("Expected the confirmed owner MID")
    return f"bilibili:{owner_mid}:project:{project_id}"


def validate_registration(value, owner_mid):
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or not value[key].strip()
        for key in (
            "businessKey",
            "platform",
            "accountId",
            "objectId",
            "url",
            "publishedAt",
            "mainReviewReceipt",
            "evidenceSha256",
        )
    ):
        raise ValueError("Expected a reviewed publication registration")
    bvid = value["objectId"]
    bilibili.source_identity(bvid, owner_mid)
    published = datetime.fromisoformat(value["publishedAt"])
    if (
        value["platform"] != "bilibili"
        or value["accountId"] != str(owner_mid)
        or value["url"] != f"https://www.bilibili.com/video/{bvid}/"
        or not re.fullmatch(r"[a-f0-9]{64}", value["evidenceSha256"])
        or published.tzinfo is None
    ):
        raise ValueError("Publication registration identity or evidence differs")
    return bvid


def publications(project, project_id, owner_mid):
    identity(project_id, owner_mid)
    root = project.resolve(strict=True)
    path = root / ".roami/okr/data/collection.sqlite3"
    if not path.resolve(strict=True).is_relative_to(root) or path.is_symlink():
        raise ValueError("Publication registry escapes this project")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("projectId") != project_id or metadata.get("schemaVersion") != "1":
            raise ValueError("Publication registry identifies another project or schema")
        rows = connection.execute(
            "SELECT content, sha256 FROM publications WHERE platform=? AND account_id=? ORDER BY business_key",
            ("bilibili", str(owner_mid)),
        ).fetchmany(4097)
    if not 1 <= len(rows) <= 4096:
        raise ValueError(
            "Expected 1..4096 reviewed project publications; reconcile coverage before collecting"
        )
    result = []
    seen = set()
    for content, digest in rows:
        value = json.loads(content)
        if sha256(value) != digest:
            raise ValueError("Publication registry digest differs")
        bvid = validate_registration(value, owner_mid)
        if bvid in seen:
            raise ValueError("Duplicate or mismatched publication URL")
        seen.add(bvid)
        result.append({"publication": value, "sha256": digest})
    return result


def verified_counts(snapshot, owner_mid):
    source, evidence = snapshot["source"], snapshot["evidence"]
    if (
        snapshot.get("candidateOnly") is not True
        or type(snapshot.get("schemaVersion")) is not int
        or snapshot["schemaVersion"] != 1
        or source.get("service") != "bilibili"
        or type(source.get("ownerMid")) is not int
        or source["ownerMid"] != owner_mid
        or source.get("identity") != bilibili.source_identity(source["bvid"], owner_mid)
        or type(evidence["http"]["status"]) is not int
        or evidence["http"]["status"] != 200
    ):
        raise ValueError("Collection identity or HTTP status differs")
    raw = evidence["http"]["body"].encode()
    payload, values = bilibili.parse_response(raw, source["bvid"], owner_mid)
    if (
        hashlib.sha256(raw).hexdigest() != evidence["sha256"]
        or payload != evidence["payload"]
        or snapshot["values"] != values
        or any(type(value) is not int for value in snapshot["values"].values())
        or type(source.get("aid")) is not int
        or source["aid"] != payload["data"]["aid"]
    ):
        raise ValueError("Collected values differ from raw platform evidence")
    return values


def aggregate(coverage, snapshots, owner_mid):
    if not 1 <= len(coverage) <= 4096 or len(coverage) != len(snapshots):
        raise ValueError("Incomplete project coverage")
    counts = []
    seen = set()
    for registration, snapshot in zip(coverage, snapshots, strict=True):
        publication = registration["publication"]
        bvid = validate_registration(publication, owner_mid)
        if (
            registration["sha256"] != sha256(publication)
            or publication["accountId"] != str(owner_mid)
            or publication["platform"] != "bilibili"
            or snapshot["source"]["bvid"] != bvid
            or bvid in seen
        ):
            raise ValueError("Collection differs from the frozen publication set")
        seen.add(bvid)
        counts.append(verified_counts(snapshot, owner_mid))
    values = {}
    for field in bilibili.FIELDS:
        if all(field in row for row in counts):
            value = sum(row[field] for row in counts)
            if value > bilibili.MAX_COUNT:
                raise ValueError("Project cumulative count exceeds safe integer range")
            values[field] = value
    if not values:
        raise ValueError("No field has complete project coverage")
    return values


def collect(project, project_id, owner_mid, timezone):
    source_identity = identity(project_id, owner_mid)
    zone = ZoneInfo(timezone)
    coverage = publications(project, project_id, owner_mid)
    snapshots = [
        bilibili.collect(row["publication"]["objectId"], owner_mid, timezone) for row in coverage
    ]
    values = aggregate(coverage, snapshots, owner_mid)
    captured = datetime.now(UTC)
    result = {
        "schemaVersion": 1,
        "candidateOnly": True,
        "source": {
            "service": "bilibili",
            "identity": source_identity,
            "projectId": project_id,
            "ownerMid": owner_mid,
        },
        "coverage": coverage,
        "coverageSha256": sha256(coverage),
        "snapshots": snapshots,
        "values": values,
        "capturedAt": captured.isoformat(),
        "asOf": captured.astimezone(zone).date().isoformat(),
    }
    if len(encoded(result).encode()) > 4 * bilibili.MAX_BYTES:
        raise ValueError("Project evidence exceeds candidate byte limit")
    return result


def prepare(workspace, candidate, connector_id, batch_id, evidence_path):
    source = candidate["source"]
    owner_mid = source["ownerMid"]
    source_identity = identity(source["projectId"], owner_mid)
    workspace = workspace.get("data", workspace)
    if workspace.get("projectId") != source["projectId"]:
        raise ValueError("Candidate identifies another project")
    if source.get("identity") != source_identity or source.get("service") != "bilibili":
        raise ValueError("Candidate source differs")
    if (
        type(candidate.get("schemaVersion")) is not int
        or candidate["schemaVersion"] != 1
        or candidate.get("candidateOnly") is not True
    ):
        raise ValueError("Expected an unpublished project candidate")
    if candidate.get("coverageSha256") != sha256(candidate["coverage"]):
        raise ValueError("Publication coverage digest differs")
    counts = aggregate(candidate["coverage"], candidate["snapshots"], owner_mid)
    if candidate["values"] != counts or any(
        type(value) is not int for value in candidate["values"].values()
    ):
        raise ValueError("Project cumulative values differ from primary evidence")
    raw = encoded(candidate).encode()
    if len(raw) > 4 * bilibili.MAX_BYTES:
        raise ValueError("Project evidence exceeds byte limit")
    if not workspace.get("projectFiles", {}).get("connectorSkillBatches"):
        raise ValueError("Host does not support Connector Skill batches")
    if type(workspace.get("revision")) is not int or workspace["revision"] < 1:
        raise ValueError("Read the confirmed project revision")
    if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
        raise ValueError("Use one persisted 32-lowercase-hex batch key")
    matches = [row for row in workspace["connectors"] if row["id"] == connector_id]
    if len(matches) != 1:
        raise ValueError("Expected one confirmed project Connector")
    connector = matches[0]
    if (
        connector["service"] != "bilibili"
        or connector["identity"] != source_identity
        or connector["window"] != "snapshot"
    ):
        raise ValueError("Confirmed Connector identity or window differs")
    if not re.fullmatch(r"[a-f0-9]{64}", connector.get("packageSha256", "")):
        raise ValueError("Connector package has no confirmed digest")
    captured = datetime.fromisoformat(candidate["capturedAt"])
    zone = ZoneInfo(connector["timezone"])
    if captured.tzinfo is None or captured.astimezone(zone).date().isoformat() != candidate["asOf"]:
        raise ValueError("Candidate timestamp differs from confirmed timezone")
    for snapshot in candidate["snapshots"]:
        at = datetime.fromisoformat(snapshot["capturedAt"])
        if (
            at.tzinfo is None
            or at > captured
            or at.astimezone(zone).date().isoformat() != candidate["asOf"]
        ):
            raise ValueError("Project snapshot crosses the claimed collection window")
    metrics = {row["id"]: row for row in workspace["metrics"]}
    values, fields, ids = [], set(), set()
    for binding in connector["bindings"]:
        field, metric_id = binding["field"], binding["metricId"]
        metric = metrics[metric_id]
        if (
            field not in bilibili.FIELDS
            or field in fields
            or metric_id in ids
            or metric["source"] != "manual"
            or not isinstance(metric["unit"], str)
        ):
            raise ValueError("Confirmed metric mapping differs")
        fields.add(field)
        ids.add(metric_id)
        if field in counts:
            values.append({"metricId": metric_id, "unit": metric["unit"], "value": counts[field]})
    if not values:
        raise ValueError("No bound metric has complete coverage")
    return {
        "revision": workspace["revision"],
        "batch": {
            "id": batch_id,
            "connectorId": connector_id,
            "packageSha256": connector["packageSha256"],
            "sourceIdentity": source_identity,
            "date": candidate["asOf"],
            "capturedAt": candidate["capturedAt"],
            "windowStart": candidate["capturedAt"],
            "windowEnd": candidate["capturedAt"],
            "values": values,
            "evidence": [{"path": evidence_path, "sha256": hashlib.sha256(raw).hexdigest()}],
        },
    }, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    fetch = sub.add_parser("fetch")
    for name in ("project", "project-id", "timezone"):
        fetch.add_argument("--" + name, required=True)
    fetch.add_argument("--owner-mid", required=True, type=int)
    batch = sub.add_parser("prepare")
    for name in (
        "workspace",
        "candidate",
        "connector",
        "batch-id",
        "project",
        "evidence",
        "output",
    ):
        batch.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "fetch":
            result = collect(Path(args.project), args.project_id, args.owner_mid, args.timezone)
        else:
            project = Path(args.project).resolve(strict=True)
            evidence = bilibili.destination(project, args.evidence)
            output = bilibili.destination(project, args.output)
            if evidence == output:
                raise ValueError("Keep request and evidence in separate files")
            request, raw = prepare(
                bilibili.read_json(args.workspace),
                bilibili.read_json(args.candidate),
                args.connector,
                args.batch_id,
                evidence.relative_to(project).as_posix(),
            )
            bilibili.write_once(evidence, raw)
            bilibili.write_once(output, (encoded(request) + "\n").encode())
            result = {
                "candidateOnly": True,
                "requestFile": args.output,
                "evidenceFile": args.evidence,
                "batchId": args.batch_id,
            }
        print(encoded(result))
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
