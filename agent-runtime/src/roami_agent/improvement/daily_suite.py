"""Frozen daily coverage contract; sixty unrelated records are not the agreed suite."""

import re
from collections import Counter

from roami_agent.improvement.contracts import digest, freeze_suite, require, validate_suite

PUBLIC_QUOTAS = {
    "swe_verified": 2,
    "terminal_bench": 2,
    "the_agent_company": 2,
    "osworld": 2,
    "agentic_vbench": 2,
    "dsbench": 2,
    "spreadsheetbench": 1,
    "gaia": 1,
    "longmemeval_v2": 1,
    "finqa": 3,
    "convfinqa": 1,
    "mlagentbench": 1,
}
AUTHORED_IDS = frozenset(
    [
        "DEMO-01",
        "DEMO-02",
        "DEMO-05",
        "QUANT-01",
        "QUANT-02",
        "QUANT-03",
        "QUANT-04",
        "QUANT-05",
        "NEWS-01",
        "NEWS-02",
        "NEWS-04",
        "STOCK-01",
        "STOCK-03",
        "STOCK-04",
        "STOCK-05",
        "DOC-03",
        "DOC-05",
        "LAB-05",
        "CODE-01",
        "OPS-04",
    ]
)
MECHANISM_IDS = frozenset(
    "MECH-" + domain + suffix
    for domain in ("MG", "MR", "CT", "TL", "TE", "TR", "SK", "PL", "MB", "VD")
    for suffix in ("01", "02")
)
CONTRACT = "roami-daily-60-v1"


def daily_coverage(suite):
    cases = suite["cases"]
    public = [c for c in cases if c["layer"].startswith("public_")]
    authored = {c["id"] for c in cases if c["layer"] == "authored_real"}
    mechanisms = {c["id"] for c in cases if c["layer"] == "mechanism"}
    quotas = Counter(c["origin"]["benchmark"] for c in public)
    sources = [(c["origin"]["benchmark"], c["origin"]["task_id"]) for c in public]
    checks = {
        "count": len(cases) == 60,
        "unique_ids": len({c["id"] for c in cases}) == len(cases),
        "public_quotas": quotas == PUBLIC_QUOTAS,
        "unique_public_tasks": len(set(sources)) == len(sources),
        "pinned_public_revisions": all(
            bool(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", c["origin"]["revision"]))
            for c in public
        ),
        "authored_selection": authored == AUTHORED_IDS,
        "mechanism_selection": mechanisms == MECHANISM_IDS,
        "formal_splits": all(c["split"] in {"development", "public_test"} for c in cases),
        "no_smoke": all(c["layer"] != "smoke" for c in cases),
        "mechanism_grader": all(
            c["judge"]["kind"] == "mechanism" and not c["counts_as_delivery"]
            for c in cases
            if c["layer"] == "mechanism"
        ),
    }
    return {
        "contract": CONTRACT,
        "complete": all(checks.values()),
        "checks": checks,
        "public": {k: {"expected": v, "actual": quotas[k]} for k, v in PUBLIC_QUOTAS.items()},
        "missing_authored": sorted(AUTHORED_IDS - authored),
        "missing_mechanisms": sorted(MECHANISM_IDS - mechanisms),
        "scope": "composition_only; environment and graders require separate acceptance",
    }


def assemble_daily(suite_id, suites):
    require(bool(suites), "RSI_FORMAL_SUITE_INCOMPLETE")
    for suite in suites:
        validate_suite(suite)
    result = freeze_suite(
        suite_id,
        [c for suite in suites for c in suite["cases"]],
        daily_contract=CONTRACT,
        source_suites=[{"id": s["id"], "content_hash": s["content_hash"]} for s in suites],
    )
    require(daily_coverage(result)["complete"], "RSI_FORMAL_SUITE_INCOMPLETE")
    return result


def validate_private_separation(daily, private):
    formal = daily["cases"]
    held = private["cases"]
    require(
        {c["id"] for c in formal}.isdisjoint(c["id"] for c in held)
        and {c.get("cluster", c["id"]) for c in formal}.isdisjoint(
            c.get("cluster", c["id"]) for c in held
        )
        and {
            digest({k: c.get(k) for k in ("prompt", "files", "asset_files")}) for c in formal
        }.isdisjoint(
            digest({k: c.get(k) for k in ("prompt", "files", "asset_files")}) for c in held
        ),
        "RSI_PRIVATE_CORPUS_OVERLAP",
    )
