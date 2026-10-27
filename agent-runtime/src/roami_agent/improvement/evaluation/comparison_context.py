"""Freeze execution and grading identities separately for cross-run comparisons."""

import hashlib
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.integrations.source_identity import implementation_hash


def grading_hash(suite, executor):
    grading = grading_sources()
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


def grading_sources():
    root = Path(__file__).parents[1]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("domain", "evaluation")
        for path in sorted((root / folder).rglob("*.py"))
    }
