"""Freeze execution and grading identities separately for cross-run comparisons."""

import hashlib
from pathlib import Path

from roami_agent.improvement.contracts import digest, implementation_hash


def grading_hash(suite, executor):
    root = Path(__file__).parent
    grading = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "grading.py",
            "authored_grading.py",
            "artifact_review.py",
            "artifact_evidence.py",
        )
    }
    reviewer = getattr(executor, "artifact_reviewer", None)
    return digest(
        [
            grading,
            {case["id"]: case["judge"] for case in suite["cases"]},
            getattr(reviewer, "content_hash", None),
        ]
    )


def comparison_context(suite, executor, machine, *, source_hash=None):
    return {
        "source_hash": source_hash or implementation_hash(),
        "model_hash": executor.model_hash,
        "environment_hash": machine["environment_hash"],
        "judge_hash": grading_hash(suite, executor),
    }
