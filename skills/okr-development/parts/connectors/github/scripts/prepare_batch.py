"""Prepare a reviewed GitHub candidate for Main; never publish or execute a scheduler."""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Input exceeds limit")
    return json.loads(data)


def destination(project, name):
    if any(char in name for char in "\\:%?#"):
        raise ValueError("Output contains unsupported path characters")
    relative = Path(name)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(p in {".", ".."} for p in relative.parts)
    ):
        raise ValueError("Output must be a project-relative file")
    current = project
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Output symlinks are not allowed")
    if not current.resolve().is_relative_to(project):
        raise ValueError("Output escapes project")
    return current


def write_once(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != body:
            raise ValueError(
                "Existing output differs; reconcile it instead of overwriting"
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
    if len(matches) != 1 or matches[0]["service"] != "github":
        raise ValueError("Expected a confirmed GitHub Skill binding")
    connector = matches[0]
    if connector["window"] != "snapshot" or connector["timezone"] != "Asia/Shanghai":
        raise ValueError("GitHub snapshot contract changed")
    if not re.fullmatch(r"[a-f0-9]{64}", connector.get("packageSha256", "")):
        raise ValueError("Skill package has no confirmed digest")
    if (
        candidate.get("candidateOnly") is not True
        or candidate.get("schemaVersion") != 1
    ):
        raise ValueError("Expected a fetch_github candidate")
    source = candidate["source"]
    if (
        source["service"] != "github"
        or str(source["repositoryId"]) != connector["identity"]
        or source["repo"].casefold() != connector["repo"].casefold()
    ):
        raise ValueError("Candidate source differs from the confirmed binding")
    if candidate["evidence"]["http"]["status"] != 200:
        raise ValueError("Candidate is not an HTTP 200 response")
    raw = candidate["evidence"]["http"]["body"].encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw)
    if (
        digest != candidate["evidence"]["sha256"]
        or payload != candidate["evidence"]["payload"]
    ):
        raise ValueError("Raw evidence differs from the candidate")
    if (
        type(payload.get("id")) is not int
        or str(payload["id"]) != connector["identity"]
        or payload["full_name"].casefold() != connector["repo"].casefold()
        or payload.get("private") is not False
    ):
        raise ValueError("Raw response is not the confirmed public repository")
    captured = datetime.fromisoformat(candidate["capturedAt"])
    if (
        captured.tzinfo is None
        or captured.astimezone(ZoneInfo(connector["timezone"])).date().isoformat()
        != candidate["asOf"]
    ):
        raise ValueError("Candidate date does not match the confirmed timezone")
    metrics = {m["id"]: m for m in workspace["metrics"]}
    values = []
    for binding in connector["bindings"]:
        field = binding["field"]
        metric = metrics[binding["metricId"]]
        if (
            field not in {"stars", "forks"}
            or metric["source"] != "github"
            or metric["field"] != field
            or metric["repo"].casefold() != connector["repo"].casefold()
        ):
            raise ValueError("Metric mapping changed")
        count = payload["stargazers_count" if field == "stars" else "forks_count"]
        if (
            type(count) is not int
            or not 0 <= count <= 9007199254740991
            or candidate["values"][field] != count
        ):
            raise ValueError("Candidate contains an invalid or altered count")
        values.append(
            {"metricId": metric["id"], "unit": metric["unit"], "value": count}
        )
    return {
        "revision": workspace["revision"],
        "batch": {
            "id": batch_id,
            "connectorId": connector_id,
            "packageSha256": connector["packageSha256"],
            "sourceIdentity": connector["identity"],
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
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--connector", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        project = Path(args.project).resolve(strict=True)
        evidence = destination(project, args.evidence)
        output = destination(project, args.output)
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
            json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode()
        write_once(evidence, raw)
        write_once(output, body)
        print(
            json.dumps(
                {
                    "candidateOnly": True,
                    "requestFile": args.output,
                    "evidenceFile": args.evidence,
                    "batchId": args.batch_id,
                }
            )
        )
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
