"""Trusted code-version A/B and private promotion gates outside the repair context."""

import asyncio
import json
from pathlib import Path

from roami_agent.improvement.comparison import compare
from roami_agent.improvement.containers import ContainerExecutor
from roami_agent.improvement.contracts import digest, load_suite, require
from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.cycle import run_cycle
from roami_agent.improvement.daily_suite import daily_coverage, validate_private_separation
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.source_revision import allowed, source_hash


def problem_improved(finding, baseline, candidate):
    if not candidate["grade"]["passed"]:
        return False
    metric = finding.get("acceptance_metric", "tokens")
    if metric == "quality":
        return candidate["grade"]["quality"] > baseline["grade"]["quality"]
    if metric == "repeated_read":

        def count(trial):
            return sum(f["code"] == "repeated_read" for f in trial["log_review"]["findings"])

        return count(candidate) < count(baseline)
    require(metric in {"tokens", "elapsed_ms"}, "RSI_INVALID_ACCEPTANCE")
    a, b = baseline["metrics"].get(metric), candidate["metrics"].get(metric)
    return a is not None and b is not None and a > 0 and b < a


class CodePairExecutor:
    def __init__(self, settings, candidate, *, provider_factory=None, artifact_reviewer=None):
        tests = Path(candidate["baseline_root"]) / "agent-runtime/tests"
        self.executors = {
            arm: ContainerExecutor(
                settings,
                source_root=candidate[arm + "_root"],
                regression_root=tests,
                provider_factory=provider_factory,
                artifact_reviewer=artifact_reviewer,
            )
            for arm in ("baseline", "candidate")
        }
        self.model_hash = self.executors["baseline"].model_hash
        self.builds = {arm: candidate[arm + "_build_hash"] for arm in self.executors}

    async def preflight(self):
        fingerprints = await asyncio.gather(*(e.preflight() for e in self.executors.values()))
        require(fingerprints[0] == fingerprints[1], "RSI_CODE_ENVIRONMENT_MISMATCH")
        for arm, e in self.executors.items():
            require(source_hash(e.source_root) == self.builds[arm], "RSI_SOURCE_CHANGED")
        return fingerprints[0]

    def reservation_tokens(self, case):
        return self.executors["baseline"].reservation_tokens(case)

    async def run_arm(self, arm, case, policy, root):
        e = self.executors[arm]
        require(source_hash(e.source_root) == self.builds[arm], "RSI_SOURCE_CHANGED")
        result = await e.run(case, policy, root)
        require(source_hash(e.source_root) == self.builds[arm], "RSI_SOURCE_CHANGED")
        return result

    async def regression(self, root):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        program = """import json,subprocess,sys
p=subprocess.run([sys.executable,"-m","pytest","-q","--asyncio-mode=auto","--ignore-glob=/opt/roami-agent/tests/test_improvement*.py","-p","no:cacheprovider","--basetemp=/tmp/rsi-tests","/opt/roami-agent/tests"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
print(json.dumps({"scope":"frozen_runtime_regressions","exit_code":p.returncode,"output":p.stdout.decode(errors="replace")[-500000:]}))"""
        raw = await self.executors["candidate"].sandbox(root, program, timeout=600, runtime=True)
        result = json.loads(raw)
        try:
            private_json(root / ("regression-" + digest(result)[:16] + ".json"), result)
        except FileExistsError:
            pass
        require(result["exit_code"] == 0, "RSI_CANDIDATE_REGRESSION_FAILED")
        return result


def checked_evidence(ledger, owner, cycles, builds):
    arms = {"baseline": [], "candidate": []}
    for repetition, cycle_id in enumerate(cycles):
        cycle = ledger.get(owner, cycle_id)
        require(
            cycle["state"] == "completed" and cycle["manifest"].get("source_builds") == builds,
            "RSI_EVIDENCE_MISMATCH",
        )
        expected = set(cycle["manifest"]["case_ids"])
        require(len(cycle["trials"]) == 2 * len(expected), "RSI_EVIDENCE_INCOMPLETE")
        for arm, arm_trials in arms.items():
            trials = [t for t in cycle["trials"] if t["arm"] == arm]
            require({t["case_id"] for t in trials} == expected, "RSI_EVIDENCE_INCOMPLETE")
            for t in trials:
                require(
                    t.get("agent_build_hash") == builds[arm]
                    and t.get("log_review", {}).get("complete"),
                    "RSI_EVIDENCE_MISMATCH",
                )
                arm_trials.append({**t, "repetition": repetition})
    return compare(arms["baseline"], arms["candidate"])


async def verify_candidate(
    workflow, action, settings, config, *, executor_factory=CodePairExecutor
):
    candidate = action["payload"]
    require(all(allowed(p, config) for p in candidate["paths"]), "RSI_PROTECTED_SOURCE")
    control = ImprovementControl(workflow.ledger)
    prefs = control.preferences(action["owner"])
    require(config["validation_suite_id"], "RSI_PRIVATE_VALIDATION_REQUIRED")
    ids = [prefs["suite_id"], config["validation_suite_id"]]
    suites = []
    with workflow.ledger.connection() as db:
        for suite_id in ids:
            row = db.execute(
                "SELECT * FROM rsi_suites WHERE owner=? AND id=?", (action["owner"], suite_id)
            ).fetchone()
            require(row is not None, "RSI_SUITE_NOT_FOUND")
            value = load_suite(Path(row["path"]))
            require(value["content_hash"] == row["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            suites.append(value)
        origin = db.execute(
            "SELECT manifest_json FROM rsi_cycles WHERE id=? AND owner=?",
            (candidate["finding"]["cycle_id"], action["owner"]),
        ).fetchone()
    require(origin is not None, "RSI_EVIDENCE_MISMATCH")
    require(daily_coverage(suites[0])["complete"], "RSI_FORMAL_SUITE_INCOMPLETE")
    validate_private_separation(*suites)
    private = suites[1]["cases"]
    require(
        all(c["split"] in {"holdout", "validation"} for c in private), "RSI_PRIVATE_SPLIT_REQUIRED"
    )
    clusters = {
        split: {c.get("cluster", c["id"]) for c in private if c["split"] == split}
        for split in ("holdout", "validation")
    }
    require(
        len(clusters["holdout"]) >= 30
        and len(clusters["validation"]) >= 24
        and clusters["holdout"].isdisjoint(clusters["validation"]),
        "RSI_PRIVATE_VALIDATION_REQUIRED",
    )
    if executor_factory is CodePairExecutor:
        from roami_agent.improvement.artifact_review import ArtifactReviewer, needs_artifact_review

        reviewer = ArtifactReviewer.load(settings, workflow.ledger.path.parent, action["owner"])
        require(
            reviewer is not None
            or not any(needs_artifact_review(c) for s in suites for c in s["cases"]),
            "RSI_ARTIFACT_REVIEW_REQUIRED",
        )
        executor = executor_factory(settings, candidate, artifact_reviewer=reviewer)
    else:
        executor = executor_factory(settings, candidate)
    fingerprint = await executor.preflight()
    day = workflow.day(action["owner"])
    with workflow.ledger.connection() as db:
        budget = db.execute(
            "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (action["owner"], day)
        ).fetchone()
        needed = 2 * sum(executor.reservation_tokens(c) for s in suites for c in s["cases"])
        episodes = 2 * sum(len(s["cases"]) for s in suites)
        require(
            budget
            and budget["tokens_reserved"] + needed <= budget["tokens_limit"]
            and budget["episodes_reserved"] + episodes <= budget["episodes_limit"],
            "RSI_DAILY_BUDGET",
        )
    checks = await executor.regression(workflow.ledger.path.parent / "checks" / action["id"])
    machine = {**json.loads(origin[0])["machine"], **fingerprint}
    require(machine["cache_mode"] in {"cold", "warm"}, "RSI_CONTROLLED_CACHE_REQUIRED")
    cycles = []
    policy = json.loads(origin[0])["baseline_policy"]
    for i, suite in enumerate(suites):
        result = await run_cycle(
            ledger=workflow.ledger,
            owner=action["owner"],
            day=day,
            suite=suite,
            machine=machine,
            executor=executor,
            baseline=policy,
            candidate=policy,
            output_root=workflow.ledger.path.parent / "runs",
            daily_tokens=budget["tokens_limit"],
            daily_episodes=budget["episodes_limit"],
            request_key=action["id"] + ":" + str(i),
            source_builds=executor.builds,
        )
        cycles.append(result["cycle_id"])
    comparison = checked_evidence(workflow.ledger, action["owner"], cycles, executor.builds)
    formal = workflow.ledger.get(action["owner"], cycles[0])
    problem = {
        t["arm"]: t for t in formal["trials"] if t["case_id"] == candidate["finding"]["case_id"]
    }
    require(
        set(problem) == {"baseline", "candidate"}
        and problem_improved(candidate["finding"], problem["baseline"], problem["candidate"]),
        "RSI_ORIGINAL_PROBLEM_UNRESOLVED",
    )
    require(comparison["eligible_for_promotion"], "RSI_PROMOTION_REJECTED")
    return {
        **candidate,
        "verification_cycles": cycles,
        "comparison": comparison,
        "regression_output_hash": digest(checks),
        "verified_by": "host_code_verifier_v1",
    }
