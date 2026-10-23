"""Frozen experiment inputs; evaluation data never belongs to the agent view."""

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from roami_agent.protocol.errors import DomainError

VERSION = "roami-rsi-runner-v1"
DIMENSIONS = ("correctness", "completeness", "usability", "grounding")
LAYERS = {"public_agent", "public_component", "authored_real", "mechanism", "smoke"}
SPLITS = {"development", "validation", "holdout", "public_test"}


@lru_cache(maxsize=1)
def implementation_hash():
    root = Path(__file__).parents[1]
    return digest(
        {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))
        }
    )


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


def relative_file(root, name):
    require(isinstance(name, str) and bool(name) and not Path(name).is_absolute())
    path = root / name
    require(".." not in Path(name).parts and path.resolve().is_relative_to(root.resolve()))
    return path


def load_json(path, *, maximum=16_000_000):
    require(path.stat().st_size <= maximum, "RSI_INPUT_TOO_LARGE")
    return json.loads(path.read_text(), parse_constant=lambda value: require(False))


def validate_case(case):
    require(isinstance(case, dict))
    identifier(case.get("id"))
    identifier(case.get("category"))
    require(case.get("layer") in LAYERS and case.get("split") in SPLITS)
    if case["split"] in {"holdout", "validation"}:
        require(case["layer"] in {"authored_real", "mechanism"}, "RSI_PRIVATE_SPLIT_REQUIRED")
    require(isinstance(case.get("prompt"), str) and 0 < len(case["prompt"]) <= 1_000_000)
    require(type(case.get("counts_as_delivery")) is bool)
    limits = case.get("limits", {})
    require(set(limits) == {"seconds", "tokens", "requests"})
    require(number(limits["seconds"], 1, 3600))
    require(type(limits["tokens"]) is int and 1 <= limits["tokens"] <= 1_000_000)
    require(type(limits["requests"]) is int and 1 <= limits["requests"] <= 100)
    fixtures = case.get("files", {})
    require(isinstance(fixtures, dict) and len(fixtures) <= 1000)
    for name, content in fixtures.items():
        relative_file(Path("/workspace"), name)
        require(isinstance(content, str) and len(content) <= 1_000_000)
    judge = case.get("judge", {})
    require(judge.get("kind") in {"numeric", "json", "external", "rubric", "authored", "mechanism"})
    for name, content in case.get("asset_files", {}).items():
        relative_file(Path("/workspace"), name)
        require(isinstance(content, str) and len(content) <= 16_000_000)
    if judge["kind"] in {"numeric", "json"}:
        require("expected" in judge)
        if "path" in judge:
            relative_file(Path("/workspace"), judge["path"])
    if judge["kind"] == "numeric":
        require(number(judge["expected"], -1e100, 1e100))
        require(number(judge.get("tolerance", 0.0001), 0, 1e6))
    if case["layer"].startswith("public_"):
        origin = case.get("origin", {})
        for field in ("benchmark", "task_id", "revision", "source_split", "adapter_revision"):
            require(isinstance(origin.get(field), str) and bool(origin[field]))
        require(bool(re.fullmatch(r"[a-f0-9]{64}", origin.get("input_sha256", ""))))
    require(isinstance(case.get("cluster", case["id"]), str))
    require(
        isinstance(case.get("followups", []), list)
        and len(case.get("followups", [])) <= 50
        and all(isinstance(p, str) and 0 < len(p) <= 1000000 for p in case.get("followups", []))
    )
    if "turn_judges" in case:
        require(len(case["turn_judges"]) == 1 + len(case.get("followups", [])))
        for judge_ in case["turn_judges"]:
            validate_case(
                {k: v for k, v in {**case, "judge": judge_}.items() if k != "turn_judges"}
            )
    return case


def validate_suite(suite):
    require(isinstance(suite, dict) and suite.get("schema_version") == 1)
    identifier(suite.get("id"))
    require(isinstance(suite.get("cases"), list) and 1 <= len(suite["cases"]) <= 10000)
    identifiers = [validate_case(case)["id"] for case in suite["cases"]]
    require(len(identifiers) == len(set(identifiers)), "RSI_DUPLICATE_CASE")
    require(
        suite.get("content_hash")
        == digest({k: v for k, v in suite.items() if k != "content_hash"}),
        "RSI_SUITE_HASH_MISMATCH",
    )
    return suite


def freeze_suite(identifier_, cases, **metadata):
    suite = {"schema_version": 1, "id": identifier_, "cases": cases, **metadata}
    suite["content_hash"] = digest(suite)
    return validate_suite(suite)


def agent_view(case, workspace):
    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "workspace": str(workspace),
        "limits": case["limits"],
    }
