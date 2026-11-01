"""Expose completed review counts and dimensions without copying grader rationale."""

import json
import re
from pathlib import Path

from roami_agent.improvement.domain.contracts import DIMENSIONS, require
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError, public_error_code


def review_summary(receipt):
    try:
        require(isinstance(receipt, dict) and type(receipt.get("schema_version")) is int)
        require(receipt["schema_version"] == 1)
        ratings = receipt["ratings"]
        require(isinstance(ratings, list) and len(ratings) <= 2)
        expected = receipt.get("expected_raters", 2)
        completed = receipt.get("completed_raters", len(ratings))
        require(type(expected) is int and expected == 2)
        require(type(completed) is int and completed == len(ratings))
        require(
            all(
                isinstance(rating, dict)
                and rating.get("blind") is True
                and isinstance(rating.get("dimensions"), dict)
                for rating in ratings
            )
        )
        names = [rating["rater"] for rating in ratings]
        require(len(set(names)) == len(names) and set(names) <= {"artifact_a", "artifact_b"})
        for rating in ratings:
            require(set(rating["dimensions"]) == set(DIMENSIONS))
            require(all(type(v) is int and 0 <= v <= 3 for v in rating["dimensions"].values()))
        evidence_hash = receipt.get("evidence_hash")
        require(not ratings or evidence_hash is not None)
        require(evidence_hash is None or bool(re.fullmatch(r"[a-f0-9]{64}", evidence_hash)))
        error = receipt.get("error")
        require(error is None or public_error_code(error) == error)
        return {
            "evidence_hash": evidence_hash,
            "completed_raters": len(ratings),
            "expected_raters": 2,
            "scores": [
                {"rater": rating["rater"], "dimensions": dict(rating["dimensions"])}
                for rating in ratings
            ],
            "error": error,
        }
    except (DomainError, KeyError, TypeError, ValueError):
        return None


def recorded_review(root):
    if root is None:
        return None
    try:
        path = relative_file(Path(root), "artifact-review.json")
        require(not path.is_symlink() and path.stat().st_size <= 128_000)
        return review_summary(json.loads(path.read_text()))
    except (DomainError, OSError, ValueError):
        return None
