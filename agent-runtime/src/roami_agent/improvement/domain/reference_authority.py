"""Distinguish human references from explicitly authorized AI reference decisions."""

import re

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.domain.scoring import same_json

HUMAN_ONLY = "human_only"
AUTHORIZED_AI = "human_or_user_authorized_ai"


def validate_reference_policy(value):
    require(value in (HUMAN_ONLY, AUTHORIZED_AI), "RSI_ARTIFACT_REFERENCE_POLICY")
    return value


def reference_kind(anchor, policy):
    validate_reference_policy(policy)
    provenance = anchor.get("reference_provenance")
    if anchor.get("human_reference") is True:
        require(provenance is None, "RSI_ARTIFACT_REFERENCE_PROVENANCE")
        require(
            isinstance(anchor.get("human_rater"), str)
            and 1 <= len(anchor["human_rater"]) <= 100
            and bool(anchor["human_rater"].strip()),
            "RSI_ARTIFACT_REFERENCE_PROVENANCE",
        )
        return "human"
    require(policy == AUTHORIZED_AI, "RSI_ARTIFACT_REFERENCE_POLICY")
    require(
        anchor.get("human_reference") is False
        and anchor.get("human_rater") == ""
        and isinstance(provenance, dict)
        and set(provenance) == {"kind", "reviewer", "authorization", "evidence_hash", "expected"},
        "RSI_ARTIFACT_REFERENCE_PROVENANCE",
    )
    require(
        provenance["kind"] == "user_authorized_ai"
        and isinstance(provenance["reviewer"], str)
        and 1 <= len(provenance["reviewer"]) <= 100
        and bool(provenance["reviewer"].strip())
        and isinstance(provenance["authorization"], str)
        and 1 <= len(provenance["authorization"]) <= 2000
        and bool(provenance["authorization"].strip())
        and isinstance(provenance["evidence_hash"], str)
        and re.fullmatch(r"[a-f0-9]{64}", provenance["evidence_hash"])
        and provenance["evidence_hash"] == anchor.get("evidence_hash")
        and isinstance(provenance["expected"], dict)
        and same_json(provenance["expected"], anchor.get("expected")),
        "RSI_ARTIFACT_REFERENCE_PROVENANCE",
    )
    return "user_authorized_ai"
