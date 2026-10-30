"""Trusted code-version A/B and private promotion gates outside the repair context."""

import asyncio
import json
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.domain.source_acceptance import (
    compare_source_evidence,
    problem_improved,
)
from roami_agent.improvement.evaluation.daily_suite import (
    daily_coverage,
    validate_private_separation,
)
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.integrations.source_workspace import allowed, source_hash
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.improvement.persistence.control import ImprovementControl
from roami_agent.improvement.persistence.evidence_queries import (
    verification_suites,
)
from roami_agent.improvement.workflows.cycle import run_cycle


class CodePairExecutor:
    def __init__(
        self,
        settings,
        candidate,
        *,
        provider_factory=None,
        artifact_reviewer=None,
        shared_daily_limit=False,
    ):
        self.artifact_reviewer = artifact_reviewer
        tests = Path(candidate["baseline_root"]) / "agent-runtime/tests"
        self.executors = {
            arm: ContainerExecutor(
                settings,
                source_root=candidate[arm + "_root"],
                regression_root=tests,
                provider_factory=provider_factory,
                artifact_reviewer=artifact_reviewer,
                shared_daily_limit=shared_daily_limit,
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
    origin = verification_suites(workflow, action, candidate, ids, suites)
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
        from roami_agent.improvement.evaluation.artifact_review import (
            ArtifactReviewer,
            needs_artifact_review,
        )

        provider_factory = getattr(workflow, "provider_factory", None)
        reviewer = ArtifactReviewer.load(
            settings,
            workflow.ledger.path.parent,
            action["owner"],
            provider_factory=provider_factory,
            shared_daily_limit=uses_shared_model_limit(workflow.ledger),
        )
        require(
            reviewer is not None
            or not any(needs_artifact_review(c) for s in suites for c in s["cases"]),
            "RSI_ARTIFACT_REVIEW_REQUIRED",
        )
        executor = executor_factory(
            settings,
            candidate,
            artifact_reviewer=reviewer,
            provider_factory=provider_factory,
            shared_daily_limit=uses_shared_model_limit(workflow.ledger),
        )
    else:
        executor = executor_factory(settings, candidate)
    fingerprint = await executor.preflight()
    day = workflow.day(action["owner"])
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
            daily_tokens=0,
            daily_episodes=0,
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
    from roami_agent.improvement.evaluation.comparison_context import comparison_context
    from roami_agent.improvement.workflows.issue_verification import case_signals

    return {
        **candidate,
        "verification_cycles": cycles,
        "comparison": comparison,
        "regression_output_hash": digest(checks),
        "verified_by": "host_code_verifier_v1",
        "verification_context": comparison_context(
            suites[0], executor, machine, source_hash=candidate["candidate_build_hash"]
        ),
        "verified_case_signals": case_signals(
            workflow.ledger, action["owner"], formal, candidate["finding"]["case_id"]
        ),
    }


def checked_evidence(ledger, owner, cycles, builds):
    return compare_source_evidence([ledger.get(owner, cycle) for cycle in cycles], builds)
