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
    require(
        judge.get("kind")
        in {
            "numeric",
            "json",
            "external",
            "rubric",
            "authored",
            "mechanism",
            "workbook",
            "terminal",
            "python_contract",
            "media",
            "vectorization",
            "swe",
        }
    )
    if judge["kind"] == "swe":
        from roami_agent.improvement.swe_tasks import IMAGE_PATTERN, TASKS

        require(judge.get("instance_id") in TASKS)
        require(bool(re.fullmatch(IMAGE_PATTERN, judge.get("image", ""))))
        require(bool(re.fullmatch(r"[a-f0-9]{40}", judge.get("base_commit", ""))))
        require(bool(re.fullmatch(r"[a-f0-9]{64}", judge.get("archive_sha256", ""))))
        require(judge.get("production_prefix") == TASKS[judge["instance_id"]][0])
        require(judge.get("test_file") == TASKS[judge["instance_id"]][1])
        require(isinstance(judge.get("test_patch"), str) and 0 < len(judge["test_patch"]) <= 200000)
        require(
            isinstance(judge.get("archive_parts"), list) and 1 <= len(judge["archive_parts"]) <= 7
        )
        require(len(set(judge["archive_parts"])) == len(judge["archive_parts"]))
        require(all(p in case.get("asset_files", {}) for p in judge["archive_parts"]))
        for key in ("fail_to_pass", "pass_to_pass"):
            require(isinstance(judge.get(key), list) and 1 <= len(judge[key]) <= 2000)
            require(all(isinstance(t, str) and len(t) <= 2000 for t in judge[key]))
    if judge["kind"] == "vectorization":
        require(isinstance(judge.get("source"), str) and bool(judge["source"]))
        require(number(judge.get("max_time_ratio"), 0.1, 0.99))
    if judge["kind"] == "media":
        require(judge.get("media_kind") in {"assembly", "repair"})
        require(
            isinstance(judge.get("upstream_verifier"), str) and bool(judge["upstream_verifier"])
        )
        require(number(judge.get("minimum_reward"), 0.5, 1))
        require(isinstance(judge.get("golden"), dict))
        require(
            set(judge["golden"])
            == (
                set()
                if judge["media_kind"] == "assembly"
                else {"clean.wav", "window.json", "sig_bak_ovr.onnx"}
            )
        )
        require(all(isinstance(v, str) and len(v) <= 4_000_000 for v in judge["golden"].values()))
    if judge["kind"] == "python_contract":
        relative_file(Path("/workspace"), judge["module"])
        require(isinstance(judge.get("probes"), list) and 1 <= len(judge["probes"]) <= 50)
        require(
            isinstance(judge.get("expected"), list)
            and len(judge["probes"]) == len(judge["expected"])
        )
    if judge["kind"] == "terminal":
        require(
            isinstance(judge.get("upstream_verifier"), str) and bool(judge["upstream_verifier"])
        )
        require(judge.get("test_driver") is None or isinstance(judge["test_driver"], str))
    if judge["kind"] == "workbook":
        require("input.xlsx" in case.get("asset_files", {}))
        relative_file(Path("/workspace"), judge["path"])
        require(isinstance(judge.get("expected"), dict) and bool(judge["expected"]))
        require(isinstance(judge.get("sheet"), str) and bool(judge["sheet"]))
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
