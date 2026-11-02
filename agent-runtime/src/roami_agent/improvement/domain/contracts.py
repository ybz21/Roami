"""Case identities, paths and invariants without benchmark or storage dependencies."""

import hashlib
import json
import math
import re

from roami_agent.protocol.errors import DomainError

VERSION = "roami-rsi-runner-v1"


MAX_SUITE_BYTES = 256_000_000


DIMENSIONS = ("correctness", "completeness", "usability", "grounding")


LAYERS = {"public_agent", "public_component", "authored_real", "mechanism", "smoke"}


SPLITS = {"development", "validation", "holdout", "public_test"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def require(condition, code="RSI_INVALID_CONTRACT"):
    if not condition:
        raise DomainError(code)


def number(value, lower, upper):
    return type(value) in {int, float} and math.isfinite(value) and lower <= value <= upper


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", value))
    return value


def evaluation_arms(manifest):
    arms = manifest.get("trial_arms", ["baseline", "candidate"])
    require(arms in (["baseline"], ["baseline", "candidate"]), "RSI_INVALID_EVALUATION_ARMS")
    return arms
