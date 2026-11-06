"""Collect a public video's candidate statistics or prepare a reviewed batch; never publish."""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FIELDS = ("view", "like", "danmaku", "reply", "share", "favorite")
MAX_BYTES = 1_048_576
MAX_COUNT = 9_007_199_254_740_991


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise ValueError("Video redirects require source reconciliation")


def source_identity(bvid, owner_mid):
    if not isinstance(bvid, str) or not re.fullmatch(r"BV[A-Za-z0-9]{10}", bvid):
        raise ValueError("Expected a complete BVID")
    if type(owner_mid) is not int or not 0 < owner_mid <= MAX_COUNT:
        raise ValueError("Expected a positive owner MID")
    return f"bilibili:{owner_mid}:{bvid}"


def parse_response(raw, bvid, owner_mid):
    source_identity(bvid, owner_mid)
    if len(raw) > MAX_BYTES:
        raise ValueError("Video response exceeds limit")
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 0
        or not isinstance(payload.get("data"), dict)
    ):
        raise ValueError("Public video API did not return a successful response")
    video = payload["data"]
    if (
        video.get("bvid") != bvid
        or not isinstance(video.get("owner"), dict)
        or type(video["owner"].get("mid")) is not int
        or video["owner"]["mid"] != owner_mid
        or type(video.get("aid")) is not int
        or not 0 < video["aid"] <= MAX_COUNT
        or type(video.get("state")) is not int
        or video["state"] != 0
        or not isinstance(video.get("stat"), dict)
    ):
        raise ValueError(
            "Public video identity or state differs from the confirmed source"
        )
    stats = video["stat"]
    if "aid" in stats and (
        type(stats["aid"]) is not int or stats["aid"] != video["aid"]
    ):
        raise ValueError("Statistics identify another video")
    values = {}
    for field in FIELDS:
        if field not in stats:
            continue
        count = stats[field]
        if type(count) is not int or not 0 <= count <= MAX_COUNT:
            raise ValueError("Public statistics contain an invalid count")
        values[field] = count
    if not values:
        raise ValueError("Public video response contains no supported statistics")
    return payload, values


def collect(bvid, owner_mid, timezone_name):
    identity = source_identity(bvid, owner_mid)
    zone = ZoneInfo(timezone_name)
    request = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/view?bvid=" + bvid,
        headers={"Accept": "application/json", "User-Agent": "roami-okr-connector"},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError("Expected an HTTP 200 video response")
        headers = {
            key: response.headers[key]
            for key in ("Date", "Content-Type")
            if key in response.headers
        }
        raw = response.read(MAX_BYTES + 1)
    payload, values = parse_response(raw, bvid, owner_mid)
    captured = datetime.now(UTC)
    return {
        "schemaVersion": 1,
        "candidateOnly": True,
        "source": {
            "service": "bilibili",
            "identity": identity,
            "bvid": bvid,
            "ownerMid": owner_mid,
            "aid": payload["data"]["aid"],
        },
        "asOf": captured.astimezone(zone).date().isoformat(),
        "capturedAt": captured.isoformat(),
        "values": values,
        "evidence": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "payload": payload,
            "http": {"status": 200, "headers": headers, "body": raw.decode("utf-8")},
        },
    }


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(4 * MAX_BYTES + 1)
    if len(raw) > 4 * MAX_BYTES:
        raise ValueError("Input exceeds limit")
    return json.loads(raw)


def destination(project, name):
    if (
        not name
        or any(char in name for char in "\\:%?#")
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Output must be a project-relative file without traversal")
    target = project
    for part in Path(name).parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Output symlinks are not allowed")
    if not target.resolve().is_relative_to(project):
        raise ValueError("Output escapes project")
    return target


def write_once(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != body:
            raise ValueError(
                "Existing output differs; reconcile instead of overwriting"
            ) from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(workspace, candidate, connector_id, batch_id, evidence_path):
    workspace = workspace.get("data", workspace)
    if not workspace.get("projectFiles", {}).get("connectorSkillBatches"):
        raise ValueError("Host does not support Connector Skill batches")
    if type(workspace.get("revision")) is not int or workspace["revision"] < 1:
        raise ValueError("Read a confirmed project revision first")
    if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
        raise ValueError("Use one persisted 32-lowercase-hex batch key")
    matches = [c for c in workspace.get("connectors", []) if c["id"] == connector_id]
    if len(matches) != 1 or matches[0]["service"] != "bilibili":
        raise ValueError("Expected a confirmed Bilibili Skill binding")
    connector = matches[0]
    if connector["window"] != "snapshot":
        raise ValueError("Public video counts require a snapshot window")
    zone = ZoneInfo(connector["timezone"])
    if not re.fullmatch(r"[a-f0-9]{64}", connector.get("packageSha256", "")):
        raise ValueError("Skill package has no confirmed digest")
    if (
        candidate.get("candidateOnly") is not True
        or type(candidate.get("schemaVersion")) is not int
        or candidate["schemaVersion"] != 1
    ):
        raise ValueError("Expected a Bilibili candidate")
    source = candidate["source"]
    identity = source_identity(source["bvid"], source["ownerMid"])
    if (
        source["service"] != "bilibili"
        or source["identity"] != identity
        or connector["identity"] != identity
    ):
        raise ValueError("Candidate source differs from the confirmed binding")
    evidence = candidate["evidence"]
    if type(evidence["http"]["status"]) is not int or evidence["http"]["status"] != 200:
        raise ValueError("Candidate is not an HTTP 200 response")
    raw = evidence["http"]["body"].encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    payload, counts = parse_response(raw, source["bvid"], source["ownerMid"])
    if digest != evidence["sha256"] or payload != evidence["payload"]:
        raise ValueError("Raw evidence differs from the candidate")
    if type(source.get("aid")) is not int or source["aid"] != payload["data"]["aid"]:
        raise ValueError("Candidate video ID differs from raw evidence")
    if candidate["values"] != counts or any(
        type(v) is not int for v in candidate["values"].values()
    ):
        raise ValueError("Candidate contains altered counts")
    captured = datetime.fromisoformat(candidate["capturedAt"])
    if (
        captured.tzinfo is None
        or captured.astimezone(zone).date().isoformat() != candidate["asOf"]
    ):
        raise ValueError("Candidate date does not match the confirmed timezone")
    metrics = {m["id"]: m for m in workspace["metrics"]}
    values, fields, ids = [], set(), set()
    for binding in connector["bindings"]:
        field, metric_id = binding["field"], binding["metricId"]
        metric = metrics[metric_id]
        if (
            field not in FIELDS
            or field in fields
            or metric_id in ids
            or metric["source"] != "manual"
            or not isinstance(metric["unit"], str)
        ):
            raise ValueError("Metric mapping changed")
        fields.add(field)
        ids.add(metric_id)
        if field in counts:
            values.append(
                {"metricId": metric_id, "unit": metric["unit"], "value": counts[field]}
            )
    if not values:
        raise ValueError("No confirmed metric has an observed value")
    return {
        "revision": workspace["revision"],
        "batch": {
            "id": batch_id,
            "connectorId": connector_id,
            "packageSha256": connector["packageSha256"],
            "sourceIdentity": identity,
            "date": candidate["asOf"],
            "capturedAt": candidate["capturedAt"],
            "windowStart": candidate["capturedAt"],
            "windowEnd": candidate["capturedAt"],
            "values": values,
            "evidence": [{"path": evidence_path, "sha256": digest}],
        },
    }, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--bvid", required=True)
    fetch.add_argument("--owner-mid", type=int, required=True)
    fetch.add_argument("--timezone", required=True)
    batch = commands.add_parser("prepare")
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
        if args.command == "fetch":
            result = collect(args.bvid, args.owner_mid, args.timezone)
        else:
            project = Path(args.project).resolve(strict=True)
            evidence, output = (
                destination(project, args.evidence),
                destination(project, args.output),
            )
            if evidence == output:
                raise ValueError("Keep evidence and request in separate files")
            request, raw = prepare(
                read_json(args.workspace),
                read_json(args.candidate),
                args.connector,
                args.batch_id,
                evidence.relative_to(project).as_posix(),
            )
            body = (
                json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n"
            ).encode()
            write_once(evidence, raw)
            write_once(output, body)
            result = {
                "candidateOnly": True,
                "requestFile": args.output,
                "evidenceFile": args.evidence,
                "batchId": args.batch_id,
            }
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
