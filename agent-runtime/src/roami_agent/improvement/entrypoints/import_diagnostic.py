"""Trusted local migration of the October diagnostic prototype; never a web import."""

import argparse
import json
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.domain.run_configuration import STAGES
from roami_agent.improvement.evaluation.contracts import load_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.service import ImprovementStatus


def import_diagnostic(service, owner, source):
    source = Path(source)
    manifest = json.loads((source / "manifest.json").read_text())
    require(manifest["mode"] == "diagnostic" and manifest["formal_daily"] is False)
    suite = load_suite(source / "suite.json") if (source / "suite.json").exists() else None
    records = service.runs
    config = records.settings(owner)
    snapshot = {
        "pipeline": {
            **config,
            "output_tokens": manifest["other_output_cap"],
            "memory_output_tokens": manifest["memory_output_cap"],
        },
        "imported": True,
        "formal_daily": False,
        "case_ids": [c["id"] for c in manifest["cases"]],
        "suite_hash": manifest["source_suite"],
        "host_commit": manifest["host_commit"],
        "original_limits": {c["id"]: c["limits"] for c in manifest["cases"]},
        "original_run": manifest["run_id"],
    }
    run_id = records.create(owner, "import-" + manifest["run_id"], "imported", snapshot)
    if records.get(owner, run_id)["state"] != "queued":
        return run_id
    outcomes = []
    for spec in manifest["cases"]:
        root = source / "evaluate" / spec["id"].replace(":", "_").replace("/", "_")
        result = json.loads((root / "trial.json").read_text())
        original = next(
            (c for c in (suite or {}).get("cases", []) if c["id"] == spec["id"]),
            {
                "id": spec["id"],
                "layer": "mechanism" if spec["id"].startswith("MECH-") else "authored_real",
            },
        )
        outcome = trial_summary(original, result, root)
        outcome["source_hash"] = manifest["source_case_hashes"][spec["id"]]
        records.case(owner, run_id, outcome)
        outcomes.append(outcome)
    records.observations(owner, run_id)
    records.artifact(owner, run_id, "evaluate", "results.json", outcomes)
    records.node(owner, run_id, "evaluate", "succeeded")
    records.artifact(
        owner, run_id, "review", "review.md", (source / "review/attempt-2/review.md").read_text()
    )
    records.artifact(
        owner,
        run_id,
        "review",
        "review-usage.json",
        json.loads((source / "review/attempt-2/codex-response.json").read_text())["metrics"],
    )
    records.node(owner, run_id, "review", "succeeded")
    issues = records.get(owner, run_id)["issues"]
    records.artifact(
        owner,
        run_id,
        "issue",
        "issue-plan.json",
        {i["id"]: "P2" for i in issues if i["status"] == "present"},
    )
    records.artifact(
        owner,
        run_id,
        "issue",
        "original-codex-issue.md",
        (source / "issue/attempt-2/issue.md").read_text(),
    )
    records.artifact(
        owner,
        run_id,
        "issue",
        "issue-usage.json",
        json.loads((source / "issue/attempt-2/codex-response.json").read_text())["metrics"],
    )
    for stage in STAGES[3:]:
        records.node(owner, run_id, stage, "skipped", "DIAGNOSTIC_NO_CANDIDATE")
    usage = json.loads((source / "usage.json").read_text())
    records.set_state(
        owner,
        run_id,
        "report_queued",
        {
            "cases": len(outcomes),
            "passed": sum(c["passed"] for c in outcomes),
            "generation_tokens": usage["tokens"],
            "codex_tokens": 37366,
            "imported": True,
            "formal_daily": False,
        },
    )
    return run_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    print(import_diagnostic(ImprovementStatus(args.data_root), args.owner, args.source))


if __name__ == "__main__":
    main()
