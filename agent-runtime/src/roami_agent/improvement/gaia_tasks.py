"""An openly published GAIA course task, graded by exhaustive table counterexamples."""

import hashlib
import json

from roami_agent.improvement.contracts import (
    DIMENSIONS,
    digest,
    freeze_suite,
    relative_file,
    require,
)
from roami_agent.improvement.grading import quality, same_json
from roami_agent.protocol.errors import DomainError

TASK_ID = "6f37996b-2ac7-44b0-8e68-6d28256631b4"
SOURCE_URL = "https://agents-course-unit4-scoring.hf.space/questions"


def table_counterexamples(question):
    rows = [
        [v.strip() for v in line.strip().strip("|").split("|")]
        for line in question.splitlines()
        if line.strip().startswith("|")
    ]
    require(len(rows) == 7 and len(rows[0]) == 6, "RSI_GAIA_TABLE_REQUIRED")
    labels = rows[0][1:]
    require(labels == ["a", "b", "c", "d", "e"])
    require(all(len(row) == 6 for row in rows[2:]))
    require([row[0] for row in rows[2:]] == labels)
    table = {row[0]: dict(zip(labels, row[1:], strict=True)) for row in rows[2:]}
    require(all(v in labels for row in table.values() for v in row.values()))
    pairs = [
        {"left": a, "right": b, "left_then_right": table[a][b], "right_then_left": table[b][a]}
        for a in labels
        for b in labels
        if a < b and table[a][b] != table[b][a]
    ]
    affected = sorted({p[k] for p in pairs for k in ("left", "right")})
    return pairs, affected


def import_gaia_course(source):
    raw = source.read_bytes()
    require(len(raw) <= 2_000_000, "RSI_INPUT_TOO_LARGE")
    records = json.loads(raw)
    require(isinstance(records, list))
    selected = [r for r in records if r.get("task_id") == TASK_ID]
    require(len(selected) == 1, "RSI_SOURCE_TASK_REQUIRED")
    record = selected[0]
    require(record.get("Level") == "1" and record.get("file_name") == "")
    question = record["question"]
    pairs, affected = table_counterexamples(question)
    require(bool(pairs), "RSI_GAIA_COUNTEREXAMPLE_REQUIRED")
    case = {
        "id": "gaia-course:" + TASK_ID,
        "category": "CODE",
        "layer": "public_component",
        "split": "public_test",
        "cluster": "gaia:finite-operator-counterexamples",
        "counts_as_delivery": True,
        "grading_profile": "analysis",
        "files": {"question.md": question},
        "prompt": question
        + "\n\nThis is the complete GAIA Level1 task published through the official Hugging Face Agents Course public question API, frozen locally; no gated corpus, attachment or live web access is needed. Keep question.md unchanged. Save the requested alphabetically ordered comma-separated answer to /workspace/answer.txt, without explanation. Also save /workspace/counterexamples.json as the complete JSON array of unordered counterexample pairs, one per pair with left<right, sorted by (left,right), using keys left, right, left_then_right, right_then_left. This extra proof is an RSI adaptation and is checked independently by enumerating every pair. Do not submit answers to an external leaderboard. The result measures this supplied-table reasoning contract, not the full GAIA benchmark.",
        "limits": {"seconds": 120, "tokens": 64000, "requests": 8},
        "judge": {
            "kind": "gaia_course",
            "task_id": TASK_ID,
            "input_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "counterexamples": pairs,
            "affected": affected,
        },
        "origin": {
            "benchmark": "gaia",
            "task_id": TASK_ID,
            "revision": hashlib.sha256(raw).hexdigest(),
            "source_split": "official_agents_course:gaia_validation_level1",
            "source_url": SOURCE_URL,
            "source_documentation": "https://huggingface.co/learn/agents-course/unit4/hands-on",
            "input_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "adapter_revision": "complete-table-exhaustive-proof-v1",
            "adapted": True,
            "adaptation": "Original public-course question and complete operator table. Expected result independently derived by exhaustive enumeration; added immutable-input and complete-proof assertions. Does not access the gated GAIA repository or submit to any leaderboard; not official-score comparable.",
        },
    }
    return freeze_suite(
        "gaia-course-counterexamples-v1", [case], official_leaderboard_comparable=False
    )


def grade_gaia_course(case, workspace):
    checks, evidence = {}, []
    try:
        spec = case["judge"]
        for name in ("question.md", "answer.txt", "counterexamples.json"):
            path = relative_file(workspace, name)
            require(path.is_file() and path.stat().st_size <= 100000)
            evidence.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        question = relative_file(workspace, "question.md").read_text()
        checks["input_unchanged"] = (
            hashlib.sha256(question.encode()).hexdigest() == spec["input_sha256"]
        )
        pairs, affected = table_counterexamples(question)
        checks["frozen_oracle_consistent"] = (
            same_json(pairs, spec["counterexamples"]) and affected == spec["affected"]
        )
        answer = relative_file(workspace, "answer.txt").read_text().strip()
        checks["answer"] = [v.strip() for v in answer.split(",")] == affected
        proof = json.loads(relative_file(workspace, "counterexamples.json").read_text())
        checks["complete_counterexamples"] = same_json(proof, pairs)
    except (DomainError, OSError, ValueError, KeyError, TypeError):
        checks["verification_completed"] = False
    passed = bool(checks) and all(checks.values())
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), "analysis", hard_passed=passed),
        "checks": checks,
        "evidence": evidence,
        "artifact_hash": digest(evidence),
        "native_metric": float(checks.get("answer", False)),
        "grade_scope": "official_course_task_complete_table_reasoning_with_added_proof",
        "reason": "assertions_passed" if passed else "assertion_failed",
    }
