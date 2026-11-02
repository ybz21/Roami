"""Deterministic public dataset adapters with source and sample identity locks."""

import hashlib
import json
import random
import re
from collections import defaultdict
from decimal import Decimal, localcontext

from roami_agent.improvement.domain.contracts import digest, number, require
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.daily_suite import daily_coverage


def displayed_numeric_reference(answer):
    if type(answer) in {int, float}:
        answer = str(answer)
    if not isinstance(answer, str) or len(answer) > 200:
        return None
    match = re.fullmatch(
        r"\s*([-+]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(%)?\s*",
        answer,
    )
    if not match:
        return None
    value = Decimal(match[1].replace(",", ""))
    if abs(value.as_tuple().exponent) > 200:
        return None
    with localcontext() as context:
        context.prec = 256
        unit = Decimal(1).scaleb(value.as_tuple().exponent)
        if match[2]:
            value, unit = value / 100, unit / 100
        return value, unit / 2


def stratified_sample(records, count, *, seed):
    require(type(count) is int and 1 <= count <= len(records), "RSI_SAMPLE_COUNT")
    require(len({r["id"] for r in records}) == len(records), "RSI_DUPLICATE_SOURCE_ID")
    groups = defaultdict(list)
    for record in records:
        groups[record["stratum"]].append(record)
    random_ = random.Random(seed)
    keys = sorted(groups)
    random_.shuffle(keys)
    for key in keys:
        groups[key].sort(key=lambda record: record["id"])
        random_.shuffle(groups[key])
    selected = []
    while len(selected) < count:
        for key in list(keys):
            selected.append(groups[key].pop())
            if not groups[key]:
                keys.remove(key)
            if len(selected) == count:
                break
    return selected


def import_finqa(path, *, revision, source_split, count=3, seed=20261023, conversational=False):
    require(bool(re.fullmatch(r"[a-f0-9]{40}", revision)), "RSI_PINNED_REVISION_REQUIRED")
    require(source_split in {"train", "dev", "test"})
    raw = path.read_bytes()
    require(len(raw) <= 100_000_000, "RSI_INPUT_TOO_LARGE")
    source = json.loads(raw)
    require(isinstance(source, list) and bool(source))
    records, excluded = [], []
    for item in source:
        if conversational:
            annotation = item.get("annotation", {})
            questions = annotation.get("dialogue_break", [])
            answers = annotation.get("exe_ans_list", [])
            usable = (
                bool(questions)
                and len(questions) == len(answers)
                and all(isinstance(q, str) for q in questions)
                and all(number(a, -1e100, 1e100) for a in answers)
            )
            programs = annotation.get("turn_program", [])
            identity = item.get("id")
        else:
            qa = item.get("qa", {})
            questions, answers = [qa.get("question")], [qa.get("exe_ans")]
            usable = isinstance(questions[0], str) and number(answers[0], -1e100, 1e100)
            programs = [qa.get("program", "")]
            identity = item.get("id")
        require(isinstance(identity, str) and bool(identity), "RSI_SOURCE_ID_REQUIRED")
        if not usable:
            excluded.append({"id": identity, "reason": "unsupported_non_numeric_or_missing_oracle"})
            continue
        if not conversational:
            displayed = displayed_numeric_reference(qa.get("answer"))
            if displayed is None:
                excluded.append({"id": identity, "reason": "unsupported_displayed_numeric_answer"})
                continue
            with localcontext() as context:
                context.prec = 256
                consistent = abs(Decimal(str(answers[0])) - displayed[0]) <= displayed[1]
            if not consistent:
                excluded.append(
                    {"id": identity, "reason": "inconsistent_displayed_execution_answer"}
                )
                continue
        operations = sum(str(p).count("(") for p in programs)
        stratum = ("multi" if operations > 2 else "short") + (
            "_large_table" if len(item.get("table", [])) > 6 else "_small_table"
        )
        records.append(
            {
                "id": identity,
                "stratum": stratum,
                "source": item,
                "questions": questions,
                "answers": answers,
            }
        )
    selected = stratified_sample(records, count, seed=seed)
    benchmark = "convfinqa" if conversational else "finqa"
    cases, locks = [], []
    for sample in selected:
        item = sample["source"]
        # Deliberately exclude model_input, gold_inds, programs, retrieved/gold rows and answers.
        inputs = {key: item.get(key, []) for key in ("pre_text", "table", "post_text")}
        instructions = (
            "Read the supplied financial report and answer the question. Return only one number; "
            "express percentages as decimal ratios (10% as 0.1). No percent sign, units or explanation."
            + (
                " Keep enough precision for an absolute error of at most 0.0001."
                if not conversational
                else ""
            )
            + "\n"
        )
        questions = [instructions + q for q in sample["questions"]]
        prompt = json.dumps(inputs, ensure_ascii=False) + "\n" + questions[0]
        origin = {
            "benchmark": benchmark,
            "task_id": sample["id"],
            "revision": revision,
            "source_split": source_split,
            "input_sha256": digest(inputs),
            "adapter_revision": "financial-numeric-v1"
            if conversational
            else "financial-numeric-v2-consistent-reference",
            "adapted": True,
            "adaptation": "Complete supplied report; numeric final-answer grading, not upstream program evaluation.",
        }
        case = {
            "id": benchmark + ":" + digest(sample["id"])[:16],
            "category": "FINANCE_QA",
            "cluster": benchmark + ":" + item.get("filename", sample["id"]).split("/page_")[0],
            "layer": "public_component",
            "split": "public_test" if source_split == "test" else "development",
            "prompt": prompt,
            "followups": questions[1:],
            "counts_as_delivery": True,
            "limits": {"seconds": 120, "tokens": 128000, "requests": 8},
            "files": {},
            "judge": {"kind": "numeric", "expected": sample["answers"][-1], "tolerance": 0.0001},
            "origin": origin,
        }
        if conversational:
            case["turn_judges"] = [
                {"kind": "numeric", "expected": a, "tolerance": 0.0001} for a in sample["answers"]
            ]
        cases.append(case)
        locks.append(
            {
                "case_id": case["id"],
                "upstream_id": sample["id"],
                "stratum": sample["stratum"],
                "upstream_sample_sha256": digest(item),
                "case_sha256": digest(case),
                **origin,
            }
        )
    metadata = {
        "benchmark": benchmark,
        "source_revision": revision,
        "source_split": source_split,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": seed,
        "source_records": len(source),
        "eligible_records": len(records),
        "excluded": excluded,
        "selected": locks,
        "official_leaderboard_comparable": False,
    }
    return freeze_suite(
        benchmark + ("-sample-v1" if conversational else "-sample-v2"),
        cases,
        sampling_lock=metadata,
    )


def catalog_readiness(case_bank, sampling_plan, suites):
    runnable = {c["id"] for suite in suites for c in suite["cases"]}
    public = defaultdict(set)
    for suite in suites:
        for case in suite["cases"]:
            if case["layer"].startswith("public_"):
                public[case["origin"]["benchmark"]].add(case["origin"]["task_id"])
    return {
        "target": sampling_plan["target_size"],
        "authored_bank": len(case_bank["cases"]),
        "authored_selected": len(sampling_plan["authored_case_ids"]),
        "authored_materialized": sum(i in runnable for i in sampling_plan["authored_case_ids"]),
        "public": [
            {
                "benchmark": p["benchmark_id"],
                "target": p["target_count"],
                "materialized": len(public[p["benchmark_id"]]),
                "upstream_ids": sorted(public[p["benchmark_id"]]),
            }
            for p in sampling_plan["public_sampling"]
        ],
        "daily_coverage": daily_coverage(
            {
                "cases": [
                    c
                    for suite in suites
                    for c in suite["cases"]
                    if c["split"] in {"development", "public_test"}
                ]
            }
        ),
        "private_cluster_counts": {
            split: len(
                {
                    c.get("cluster", c["id"])
                    for suite in suites
                    for c in suite["cases"]
                    if c["split"] == split
                }
            )
            for split in ("validation", "holdout")
        },
        "note": "Materialized means runnable contract, not environment ready or evaluated pass.",
    }
