"""Private artifact bytes and their owner-checked SQLite index."""

import hashlib
import json
import os
import re

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.domain.run_configuration import STAGES


class RunArtifacts:
    def __init__(self, ledger, runs):
        self.ledger, self.runs = ledger, runs
        self.root = ledger.path.parent / "pipeline-artifacts"

    def directory(self, owner, run_id):
        require(
            isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{64}", run_id), "RSI_RUN_NOT_FOUND"
        )
        path = self.root / digest(owner)[:24] / run_id
        require(not path.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def artifact(self, owner, run_id, node, name, value):
        require(
            node in STAGES and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name), "RSI_INVALID_ARTIFACT"
        )
        self.runs.get(owner, run_id)
        directory = self.directory(owner, run_id) / node
        directory.mkdir(mode=0o700, exist_ok=True)
        require(not directory.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
        path = directory / name
        raw = (
            value.encode()
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2).encode()
        )
        require(len(raw) <= 4000000, "RSI_PAYLOAD_TOO_LARGE")
        sha = hashlib.sha256(raw).hexdigest()
        with self.ledger.connection() as db:
            existing = db.execute(
                "SELECT sha256 FROM rsi_pipeline_artifacts WHERE run_id=? AND node=? AND name=?",
                (run_id, node, name),
            ).fetchone()
            if existing:
                require(existing[0] == sha, "RSI_ARTIFACT_CHANGED")
                return
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("xb") as output:
            output.write(raw)
        temp.chmod(0o600)
        with temp.open("rb") as file:
            os.fsync(file.fileno())
        temp.replace(path)
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "SELECT 1 FROM rsi_pipeline_runs WHERE id=? AND owner=?", (run_id, owner)
                ).fetchone(),
                "RSI_RUN_NOT_FOUND",
            )
            db.execute(
                "INSERT OR IGNORE INTO rsi_pipeline_artifacts VALUES(?,?,?,?,?,?,?)",
                (
                    digest([run_id, node, name]),
                    run_id,
                    node,
                    name,
                    node + "/" + name,
                    sha,
                    len(raw),
                ),
            )

    def read_artifact(self, owner, run_id, artifact_id):
        self.runs.get(owner, run_id)
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT * FROM rsi_pipeline_artifacts WHERE id=? AND run_id=?",
                (artifact_id, run_id),
            ).fetchone()
            require(row is not None, "RSI_ARTIFACT_UNAVAILABLE")
        root = self.directory(owner, run_id)
        path = root / row["path"]
        require(
            not path.is_symlink()
            and path.resolve().is_relative_to(root.resolve())
            and path.stat().st_size <= 4000000,
            "RSI_ARTIFACT_UNAVAILABLE",
        )
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == row["sha256"], "RSI_ARTIFACT_CHANGED")
        return {"name": row["name"], "text": raw.decode("utf-8"), "sha256": row["sha256"]}
