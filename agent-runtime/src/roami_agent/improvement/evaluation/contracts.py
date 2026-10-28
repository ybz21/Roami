"""Frozen experiment inputs; evaluation data never belongs to the agent view."""

import hashlib
import re
from pathlib import Path

from roami_agent.improvement.domain.contracts import (
    LAYERS,
    MAX_SUITE_BYTES,
    SPLITS,
    digest,
    identifier,
    number,
    require,
)
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.improvement.integrations.json_documents import load_json


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
            "slides",
            "long_memory",
            "company",
            "company_stock",
            "gaia_course",
        }
    )
    if judge["kind"] == "gaia_course":
        from roami_agent.improvement.evaluation.benchmarks.gaia_tasks import (
            TASK_ID,
            table_counterexamples,
        )

        require(judge.get("task_id") == TASK_ID)
        question = case.get("files", {}).get("question.md")
        require(isinstance(question, str) and 0 < len(question) <= 100000)
        require(hashlib.sha256(question.encode()).hexdigest() == judge.get("input_sha256"))
        pairs, affected = table_counterexamples(question)
        require(judge.get("counterexamples") == pairs and judge.get("affected") == affected)
    if judge["kind"] == "company_stock":
        from roami_agent.improvement.evaluation.benchmarks.stock_tasks import TASK_ID
        from roami_agent.improvement.evaluation.execution.stock_environment import IMAGE_RE

        require(judge.get("task_id") == TASK_ID)
        require(isinstance(judge.get("image"), str) and re.fullmatch(IMAGE_RE, judge["image"]))
        for key in ("raw_sha256", "golden_sha256"):
            require(bool(re.fullmatch(r"[a-f0-9]{64}", judge.get(key, ""))))
        require(isinstance(judge.get("golden"), str) and 0 < len(judge["golden"]) <= 3000000)
        import base64

        require(
            hashlib.sha256(base64.b64decode(judge["golden"], validate=True)).hexdigest()
            == judge["golden_sha256"]
        )
        require(
            all(
                isinstance(judge.get(key), str) and 0 < len(judge[key]) <= 2000000
                for key in ("verifier", "checkpoint")
            )
        )
        require(judge.get("rubric_required") is True)
    if judge["kind"] == "company":
        from roami_agent.improvement.evaluation.benchmarks.company_tasks import TASK_ID
        from roami_agent.improvement.evaluation.execution.company_environment import IMAGE_RE

        require(judge.get("task_id") == TASK_ID)
        require(isinstance(judge.get("images"), dict) and set(judge["images"]) == set(IMAGE_RE))
        require(
            all(
                isinstance(judge["images"][k], str) and re.fullmatch(pattern, judge["images"][k])
                for k, pattern in IMAGE_RE.items()
            )
        )
        require(isinstance(judge.get("db_dump"), str) and 0 < len(judge["db_dump"]) <= 6000000)
        require(bool(re.fullmatch(r"[a-f0-9]{64}", judge.get("db_sha256", ""))))
        require(
            all(
                isinstance(judge.get(key), str) and 0 < len(judge[key]) <= 2000000
                for key in ("verifier", "common_helpers", "scoring")
            )
        )
        require(judge.get("rubric_required") is True)
    if judge["kind"] == "long_memory":
        from roami_agent.improvement.evaluation.benchmarks.long_memory import EVAL_SPEC, QUESTION_ID

        require(judge.get("question_id") == QUESTION_ID and judge.get("eval_spec") == EVAL_SPEC)
        require(isinstance(judge.get("expected"), str) and 0 < len(judge["expected"]) <= 4000)
        require(isinstance(judge.get("verifier"), str) and 0 < len(judge["verifier"]) <= 200000)
        require(
            isinstance(judge.get("history_parts"), list) and 1 <= len(judge["history_parts"]) <= 6
        )
        require(len(set(judge["history_parts"])) == len(judge["history_parts"]))
        require(all(p in case.get("asset_files", {}) for p in judge["history_parts"]))
        require(bool(re.fullmatch(r"[a-f0-9]{64}", judge.get("packed_sha256", ""))))
        records = judge.get("records")
        require(isinstance(records, list) and len(records) == 100, "RSI_FULL_HISTORY_REQUIRED")
        require(all(isinstance(r, dict) and set(r) == {"id", "bytes", "sha256"} for r in records))
        require(
            all(isinstance(r["id"], str) and re.fullmatch(r"[a-f0-9]{8}", r["id"]) for r in records)
        )
        require(len({r["id"] for r in records}) == 100, "RSI_FULL_HISTORY_REQUIRED")
        require(all(type(r["bytes"]) is int and 0 < r["bytes"] <= 20000000 for r in records))
        require(
            all(
                isinstance(r["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", r["sha256"])
                for r in records
            )
        )
    if judge["kind"] == "slides":
        from roami_agent.improvement.evaluation.benchmarks.slide_tasks import TASKS

        require(judge.get("task_id") in TASKS)
        require(bool(re.fullmatch(r"[a-f0-9]{64}", judge.get("source_sha256", ""))))
        require(
            isinstance(judge.get("source_parts"), list) and 1 <= len(judge["source_parts"]) <= 8
        )
        require(len(set(judge["source_parts"])) == len(judge["source_parts"]))
        require(all(p in case.get("asset_files", {}) for p in judge["source_parts"]))
        require(isinstance(judge.get("verifier"), str) and len(judge["verifier"]) <= 2000000)
        require(isinstance(judge.get("references"), list) and len(judge["references"]) == 2)
        require(isinstance(judge.get("options"), list) and len(judge["options"]) == 2)
        for reference in judge["references"]:
            require(
                isinstance(reference, dict)
                and isinstance(reference.get("remove"), list)
                and isinstance(reference.get("replace"), dict)
            )
            require(bool(re.fullmatch(r"[a-f0-9]{64}", reference.get("content_sha256", ""))))
            require(sum(len(v) for v in reference["replace"].values()) <= 4000000)
    if judge["kind"] == "swe":
        from roami_agent.improvement.evaluation.benchmarks.swe_tasks import IMAGE_PATTERN, TASKS

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


def load_suite(path):
    return validate_suite(load_json(path, maximum=MAX_SUITE_BYTES))


def agent_view(case, workspace):
    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "workspace": str(workspace),
        "limits": case["limits"],
    }
