"""RSI handoffs, real isolated patches, independent gates and delayed closure."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.daily_suite import (
    AUTHORED_IDS,
    MECHANISM_IDS,
    PUBLIC_QUOTAS,
)
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.integrations.source_workspace import git, source_hash
from roami_agent.improvement.persistence.control import ImprovementControl
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.persistence.research_repository import ResearchRepository
from roami_agent.improvement.workflows.behavior_observer import (
    model_json,
    observe_cycle,
    record_excerpt,
)
from roami_agent.improvement.workflows.candidate_checks import checked_evidence, verify_candidate
from roami_agent.improvement.workflows.cycle import run_cycle
from roami_agent.improvement.workflows.release_observation import (
    activate_code,
    active_code,
    observe_code,
)
from roami_agent.improvement.workflows.research_worker import ResearchWorker
from roami_agent.improvement.workflows.source_revision import SourceRevisions
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings

SOURCE = "agent-runtime/src/roami_agent/context/example.py"
PATCH = f"""diff --git a/{SOURCE} b/{SOURCE}
--- a/{SOURCE}
+++ b/{SOURCE}
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
MACHINE = {"id": "fixture", "cache_mode": "cold", "environment_hash": digest("fixture")}


class Clock:
    def __init__(self):
        self.value = int(datetime.now(UTC).timestamp() * 1000)

    def __call__(self):
        return self.value

    def next_day(self):
        self.value += 86400000


class Reviewer:
    model = "fixture-not-real-model"

    def __init__(self, *, finding=False, usage=True, expand=False, protected=False):
        self.finding, self.usage, self.expand, self.protected = finding, usage, expand, protected
        self.calls = 0

    async def stream(self, messages, tools):
        self.calls += 1
        if messages[0]["content"].startswith("You are Roami's isolated"):
            value = {"patch": PATCH, "explanation": "Fixture source change"}
        elif messages[0]["content"].startswith("Write Roami's complete"):
            value = {"summary": "Fixture review summary; no real model quality claim."}
        elif "Issue Agent" in messages[0]["content"]:
            packet = json.loads(messages[1]["content"])
            value = {
                "points": [
                    {"id": p["id"], "priority": "P2", "category": "context_retention"}
                    for p in packet["points"]
                ]
            }
        else:
            packet = json.loads(messages[1]["content"])
            findings = []
            if self.finding and packet["case_id"] == "CODE-01" and packet["arm"] == "baseline":
                findings = [
                    {
                        "mechanism": "context-retention",
                        "fact": "Same immutable input read twice",
                        "hypothesis": "Context state was lost",
                        "paths": [SOURCE],
                        "evidence": [0],
                        "suggestion": "Retain the verified state",
                        "confidence": "confirmed",
                    }
                ]
            value = {"reviewed": True, "reads": [], "findings": findings}
            if self.expand and len(messages) == 2 and findings:
                value["reads"] = [{"file": "execution-log.json", "record": 0}]
                value["findings"] = []
        yield ModelEvent("text", json.dumps(value))
        if self.usage:
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )


class FixtureExecutor:
    model_hash = digest("controlled-fixture")

    def reservation_tokens(self, case):
        return 10

    async def run(self, case, policy, root):
        return await self.run_arm("baseline", case, policy, root)

    async def run_arm(self, arm, case, policy, root):
        calls = [
            {
                "id": "one",
                "state": "succeeded",
                "tool_name": "read",
                "arguments_json": '{"path":"input"}',
                "result_json": '{"value":1}',
            }
        ]
        if case["id"] == "CODE-01":
            calls.append({**calls[0], "id": "two"})
        private_json(root / "execution-log.json", {"tool_calls": calls, "traces": []})
        return {
            "execution_kind": "external_worker",
            "grade": {"quality": 80, "passed": True, "pending": False},
            "metrics": {
                "tokens": 80 if arm == "candidate" else 100,
                "elapsed_ms": 100,
                "tool_calls": len(calls),
                "model_calls": 0,
            },
            "verified_delivery": True,
            "release_blockers": [],
        }


class FixtureCodeExecutor(FixtureExecutor):
    def __init__(self, settings, candidate):
        self.candidate = candidate
        self.builds = {arm: candidate[arm + "_build_hash"] for arm in ("baseline", "candidate")}

    async def preflight(self):
        assert source_hash(self.candidate["candidate_root"]) == self.builds["candidate"]
        return {"environment_hash": MACHINE["environment_hash"]}

    async def regression(self, root):
        # Actual independent readback; the repair provider's success statement is unused.
        assert (Path(self.candidate["baseline_root"]) / SOURCE).read_text() == "VALUE = 1\n"
        assert (Path(self.candidate["candidate_root"]) / SOURCE).read_text() == "VALUE = 2\n"
        return {"exit_code": 0, "fixture_only": True}


def make_suite(count=60, *, private=False, protected=False):
    cases = [
        {
            "id": ("private-" if private else "case-") + f"{i:02d}",
            "category": "CODE",
            "layer": "authored_real",
            "split": ("holdout" if i < 30 else "validation")
            if private
            else ("public_test" if protected else "development"),
            "cluster": ("private-" if private else "dev-") + str(i),
            "prompt": ("Private fixture " if private else "Daily fixture ") + str(i),
            "counts_as_delivery": True,
            "files": {},
            "limits": {"seconds": 10, "tokens": 10, "requests": 1},
            "judge": {"kind": "numeric", "expected": 1},
        }
        for i in range(count)
    ]
    if not private:
        own = sorted(AUTHORED_IDS) + sorted(MECHANISM_IDS)
        public = [(name, i) for name, quota in PUBLIC_QUOTAS.items() for i in range(quota)]
        for i, case in enumerate(cases):
            if i < 40:
                case["id"] = own[i]
                if i >= 20:
                    case.update(
                        layer="mechanism", counts_as_delivery=False, judge={"kind": "mechanism"}
                    )
            else:
                name, index = public[i - 40]
                case.update(
                    layer="public_component",
                    origin={
                        "benchmark": name,
                        "task_id": str(index),
                        "revision": "a" * 40,
                        "input_sha256": digest([name, index]),
                        "source_split": "dev",
                        "adapter_revision": "fixture-v1",
                    },
                )
    return freeze_suite("private" if private else "daily", cases)


def seed_review_for_stage_fixture(workflow, action):
    """Lease/source-boundary tests use fixture reviews, never model evidence."""
    cycle = workflow.ledger.get(action["owner"], action["payload"]["cycle_id"])
    for trial in cycle["trials"]:
        workflow.save_review(
            action["owner"],
            cycle["id"],
            trial["arm"] + ":" + trial["case_id"],
            {"reviewed": True, "fixture_only": True},
        )


def complete_review_fixture(workflow, action, result, *, finish_issue=True):
    """Synthetic Issue receipt for tests that exercise later source/lease boundaries."""
    cycle_id = action["payload"]["cycle_id"]
    with workflow.ledger.connection() as db:
        exists = db.execute(
            "SELECT 1 FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
            (action["owner"], cycle_id),
        ).fetchone()
        findings = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT finding_json FROM rsi_improvements WHERE owner=?", (action["owner"],)
            )
        ]
    if not exists:
        points = [
            {"id": digest([f["mechanism"], sorted(f["paths"])]), "finding": f} for f in findings
        ]
        workflow.save_report(
            action,
            {
                "cycle_id": cycle_id,
                "day": workflow.day(action["owner"]),
                "sha256": digest([cycle_id, points]),
                "points": points,
                "document": "Fixture report",
            },
        )
    workflow.complete(action, result)
    if not finish_issue:
        return
    issue = workflow.claim()
    assert issue["kind"] == "issue"
    report = workflow.report(action["owner"], cycle_id)
    workflow.complete(
        issue,
        {
            "cycle_id": cycle_id,
            "issue": {
                "repository": "example/rsi-test",
                "number": 1,
                "url": "https://github.com/example/rsi-test/issues/1",
                "report_hash": report["sha256"],
                "fixture_only": True,
            },
        },
    )


async def setup(tmp_path, *, paired=True):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    await git(repo, "init", "-q")
    p = repo / SOURCE
    p.parent.mkdir(parents=True)
    p.write_text("VALUE = 1\n")
    await git(repo, "add", ".")
    await git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@localhost",
        "commit",
        "-qm",
        "fixture",
    )
    commit = (await git(repo, "rev-parse", "HEAD")).strip()
    ledger = Ledger(tmp_path / "private/ledger.sqlite3")
    clock = Clock()
    workflow = ResearchRepository(ledger, clock=clock)
    config = workflow.configure(
        "owner",
        {
            **workflow.settings("owner"),
            "enabled": True,
            "repo": str(repo),
            "base_commit": commit,
            "allowed_paths": [str(Path(SOURCE).parent)],
            "validation_suite_id": "private",
        },
    )
    control = ImprovementControl(ledger)
    control.register_machine(
        "owner", {"id": "fixture", "label": "Fixture", "mode": "container"}, local_only=True
    )
    for suite in (make_suite(), make_suite(54, private=True)):
        path = tmp_path / (suite["id"] + ".json")
        path.write_text(json.dumps(suite))
        control.register_suite("owner", path)
    prefs = {
        **control.preferences("owner"),
        "suite_id": "daily",
        "machine_ids": ["fixture"],
        "daily_tokens": 20000000,
        "daily_episodes": 1000,
        "auto_candidates": False,
    }
    control.save("owner", prefs)
    cycle = await run_cycle(
        ledger=ledger,
        owner="owner",
        day=workflow.day("owner"),
        suite=make_suite(),
        machine=MACHINE,
        executor=FixtureExecutor(),
        baseline={},
        candidate={},
        output_root=ledger.path.parent / "runs",
        daily_tokens=20000000,
        daily_episodes=1000,
        paired=paired,
    )
    return workflow, config, clock, repo, cycle


async def test_full_research_handoff_isolated_patch_independent_gate_and_two_day_close(tmp_path):
    w, cfg, clock, repo, cycle = await setup(tmp_path)
    w.discover()
    w.discover()
    action = w.claim()
    assert not w.ledger.get("owner", cycle["cycle_id"])["report"]["daily_complete"]
    assert action["kind"] == "review"
    provider = Reviewer(finding=True, expand=True)
    summary = await observe_cycle(w, action, Settings(), cfg, provider_factory=lambda _: provider)
    assert summary == {"cycle_id": cycle["cycle_id"], "semantic_reviewed": 120, "findings": 1}
    assert provider.calls == 122 and len(w.review_saved("owner", cycle["cycle_id"])) == 120
    complete_review_fixture(w, action, summary)
    assert w.ledger.get("owner", cycle["cycle_id"])["report"]["daily_complete"]
    assert len(w.snapshot("owner")["improvements"]) == 1
    repair = w.claim()
    assert repair["kind"] == "repair"
    revisions = SourceRevisions(w.ledger.path.parent / "source")
    candidate = await revisions.repair(
        w, repair, Settings(), cfg, provider_factory=lambda _: provider
    )
    assert (repo / SOURCE).read_text() == "VALUE = 1\n"
    assert (Path(candidate["candidate_root"]) / SOURCE).read_text() == "VALUE = 2\n"
    assert candidate["patch_hash"] and candidate["parent_commit"] == cfg["base_commit"]
    w.complete(repair, candidate, next_kind="verify", item_state="verifying")
    verifying = w.claim()
    verified = await verify_candidate(
        w, verifying, Settings(), cfg, executor_factory=FixtureCodeExecutor
    )
    assert verified["comparison"]["eligible_for_promotion"]
    assert len(verified["verification_cycles"]) == 2
    w.complete(verifying, verified, next_kind="activate", item_state="ready")
    activate = w.claim()
    release = await activate_code(w, activate, revisions, cfg)
    assert release["target"] == "rsi_runner" and release["commit"] != cfg["base_commit"]
    w.complete(activate, release, item_state="observing")
    assert w.snapshot("owner")["improvements"][0]["state"] == "observing"
    # A second call reconciles the existing release instead of committing or applying twice.
    assert active_code(w, "owner")["release_id"] == release["release_id"]
    for observation in range(2):
        clock.next_day()
        result = await run_cycle(
            ledger=w.ledger,
            owner="owner",
            day=w.day("owner"),
            suite=make_suite(),
            machine=MACHINE,
            executor=FixtureCodeExecutor(Settings(), candidate),
            baseline={},
            candidate={},
            source_builds={a: candidate[a + "_build_hash"] for a in ("baseline", "candidate")},
            output_root=w.ledger.path.parent / "runs",
            daily_tokens=20000000,
            daily_episodes=1000,
        )
        if observation == 0:
            manifest = w.ledger.get("owner", result["cycle_id"])["manifest"]
            for changed in (
                {**manifest, "judge_hash": digest("different-judge")},
                {
                    **manifest,
                    "machine": {
                        **manifest["machine"],
                        "environment_hash": digest("different-environment"),
                    },
                },
            ):
                with w.ledger.connection() as db:
                    db.execute(
                        "UPDATE rsi_cycles SET manifest_json=? WHERE id=?",
                        (json.dumps(changed), result["cycle_id"]),
                    )
                assert (
                    observe_code(w, "owner", result["cycle_id"])["reason"]
                    == "evaluation_context_changed"
                )
            with w.ledger.connection() as db:
                db.execute(
                    "UPDATE rsi_cycles SET manifest_json=? WHERE id=?",
                    (json.dumps(manifest), result["cycle_id"]),
                )
        w.discover()
        review = w.claim()
        assert review["kind"] == "review"
        await observe_cycle(w, review, Settings(), cfg, provider_factory=lambda _: Reviewer())
        state = observe_code(w, "owner", result["cycle_id"])
        complete_review_fixture(w, review, {"reviewed": 120})
        assert state["state"] == ("observing" if observation == 0 else "closed_fixed")
    assert not (await git(repo, "status", "--porcelain")).strip()


@pytest.mark.parametrize("unresolved", ["score", "usage"])
async def test_daily_completion_rejects_claimed_reviews_and_pending_scores(tmp_path, unresolved):
    w, _, _, _, cycle = await setup(tmp_path)
    w.discover()
    action = w.claim()
    with pytest.raises(DomainError, match="REVIEW_INCOMPLETE"):
        w.complete(action, {"semantic_reviewed": 120})
    seed_review_for_stage_fixture(w, action)
    with w.ledger.connection() as db:
        field, value = (
            ("$.grade.pending", "true") if unresolved == "score" else ("$.metrics.tokens", "null")
        )
        db.execute(
            "UPDATE rsi_trials SET record_json=json_set(record_json,?,json(?)) WHERE cycle_id=? AND arm='baseline' AND case_id='CODE-01'",
            (field, value, cycle["cycle_id"]),
        )
    complete_review_fixture(w, action, {"semantic_reviewed": 120}, finish_issue=False)
    report = w.ledger.get("owner", cycle["cycle_id"])["report"]
    assert report["semantic_review"]["complete"]
    assert not report["evaluation_complete"] and not report["daily_complete"]


async def test_unknown_paid_operation_is_never_replayed_on_resume(tmp_path):
    w, cfg, _, _, _cycle = await setup(tmp_path)
    w.discover()
    action = w.claim()
    model = Reviewer(usage=False)
    result = await model_json(
        w,
        action,
        Settings(),
        cfg,
        "one",
        [{"role": "system", "content": "You are Roami's isolated repair"}],
        provider_factory=lambda _: model,
    )
    w.block(action, "RSI_USAGE_UNKNOWN")
    assert result["metrics"]["tokens"] is None

    with pytest.raises(DomainError, match="RECONCILIATION"):
        w.resume("owner", action["id"])
    with pytest.raises(DomainError, match="RECONCILIATION"):
        await model_json(
            w,
            action,
            Settings(),
            cfg,
            "one",
            [{"role": "system", "content": "You are Roami's isolated repair"}],
            provider_factory=lambda _: model,
        )
    assert model.calls == 1
    assert w.snapshot("other")["actions"] == []
    with pytest.raises(DomainError, match="ACTION_NOT_FOUND"):
        w.resume("other", action["id"])


async def test_lease_fencing_and_duplicate_dispatch_survive_restarts(tmp_path):
    w, _, clock, _, cycle = await setup(tmp_path)
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: w.enqueue_review("owner", cycle["cycle_id"]), range(8)))
    assert len(set(ids)) == 1
    first = w.claim(lease_ms=10)
    assert w.claim() is None
    clock.value += 11
    restarted = ResearchRepository(w.ledger, clock=clock)
    second = restarted.claim()
    assert first["id"] == second["id"] and first["lease"] != second["lease"]
    with pytest.raises(DomainError, match="LEASE_LOST"):
        w.complete(first, {"fake": True})
    seed_review_for_stage_fixture(restarted, second)
    complete_review_fixture(restarted, second, {"reviewed": 120})
    assert restarted.claim() is None


async def test_protected_trials_cannot_create_optimizer_findings(tmp_path):
    w, cfg, _, _, cycle = await setup(tmp_path)
    with w.ledger.connection() as db:
        records = list(
            db.execute("SELECT * FROM rsi_trials WHERE cycle_id=?", (cycle["cycle_id"],))
        )
        for r in records:
            trial = json.loads(r["record_json"])
            trial["split"] = "holdout"
            db.execute(
                "UPDATE rsi_trials SET record_json=? WHERE cycle_id=? AND arm=? AND case_id=?",
                (json.dumps(trial), cycle["cycle_id"], r["arm"], r["case_id"]),
            )
    w.discover()
    action = w.claim()
    result = await observe_cycle(
        w, action, Settings(), cfg, provider_factory=lambda _: Reviewer(finding=True)
    )
    assert result["findings"] == 0
    assert all(r["protected"] for r in w.review_saved("owner", cycle["cycle_id"]).values())
    assert w.snapshot("owner")["improvements"] == []


async def test_legacy_budget_does_not_make_reviewer_admission_decisions(tmp_path):
    w, cfg, _, _, _ = await setup(tmp_path)
    w.discover()
    action = w.claim()
    provider = Reviewer()
    with w.ledger.connection() as db:
        db.execute("UPDATE rsi_budgets SET tokens_reserved=tokens_limit WHERE owner=?", ("owner",))
    await observe_cycle(w, action, Settings(), cfg, provider_factory=lambda _: provider)
    assert provider.calls > 0
    assert w.review_saved("owner", action["payload"]["cycle_id"])


async def test_evidence_hash_and_source_scope_are_verified(tmp_path):
    path = tmp_path / "execution-log.json"
    path.write_text('{"tool_calls":[]}')
    ref = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert record_excerpt(tmp_path, ref)["file"] == path.name
    path.write_text('{"tool_calls":[{}]}')
    with pytest.raises(DomainError, match="EVIDENCE_CHANGED"):
        record_excerpt(tmp_path, ref)
    w, cfg, _, _, _ = await setup(tmp_path / "other")
    with pytest.raises(DomainError, match="PROTECTED_SOURCE"):
        w.configure(
            "owner", {**cfg, "allowed_paths": ["agent-runtime/src/roami_agent/improvement"]}
        )


async def test_claimed_promotion_and_mutated_build_cannot_be_applied(tmp_path):
    w, _, _, _, cycle = await setup(tmp_path)
    with pytest.raises(DomainError, match="EVIDENCE_MISMATCH"):
        checked_evidence(
            w.ledger, "owner", [cycle["cycle_id"]], {"baseline": "a" * 64, "candidate": "b" * 64}
        )


async def test_worker_failure_keeps_issue_and_bounds_repair_attempts(tmp_path):
    w, _cfg, _, _, _ = await setup(tmp_path)
    w.discover()
    review = w.claim()
    f = {
        "mechanism": "bug",
        "paths": [SOURCE],
        "fact": "fixture",
        "hypothesis": "fixture",
        "suggestion": "fix",
        "cycle_id": review["subject"],
        "case_id": "CODE-01",
    }
    w.record_findings(review, [f])
    seed_review_for_stage_fixture(w, review)
    complete_review_fixture(w, review, {"done": True})
    repair = w.claim()
    w.complete(
        repair,
        {"finding": f, "attempt": 1, "improvement_id": repair["payload"]["improvement_id"]},
        next_kind="verify",
        item_state="verifying",
    )

    async def reject(action, config):
        raise DomainError("RSI_PROMOTION_REJECTED")

    service = SimpleNamespace(ledger=w.ledger, research=w)
    runtime = SimpleNamespace(settings=SimpleNamespace(current=Settings()))
    worker = ResearchWorker(runtime, service, handlers={"verify": reject})
    verify = w.claim()
    await worker.execute(verify)
    retry = w.claim()
    assert retry["kind"] == "repair" and retry["payload"]["attempt"] == 2
    assert len(w.snapshot("owner")["improvements"]) == 1
    result = {"finding": f, "attempt": 2, "improvement_id": repair["payload"]["improvement_id"]}
    w.complete(retry, result, next_kind="verify", item_state="verifying")
    await worker.execute(w.claim())
    assert w.snapshot("owner")["improvements"][0]["state"] == "blocked"
    assert w.claim() is None


async def test_executor_success_cannot_close_issue_and_transactions_rollback(tmp_path):
    w, _, _, _, _ = await setup(tmp_path)
    w.discover()
    action = w.claim()
    with pytest.raises(DomainError, match="INDEPENDENT_CLOSURE"):
        w.complete(action, {"executor_says": "success"}, item_state="closed_fixed")
    with pytest.raises(RuntimeError), w.ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE rsi_actions SET state='done' WHERE id=?", (action["id"],))
        raise RuntimeError("crash before handoff")
    assert w.snapshot("owner")["actions"][0]["state"] == "running"


async def test_source_mounts_keep_evaluation_oracles_outside_candidate_runtime(tmp_path):
    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor

    root = tmp_path / "version"
    package = root / "agent-runtime/src/roami_agent"
    (package / "context").mkdir(parents=True)
    (package / "context/example.py").write_text("VALUE=1")
    (package / "improvement").mkdir()
    (package / "improvement/case_specs.json").write_text('{"oracle":"never mount"}')
    mounts = ContainerExecutor(Settings(), source_root=root).source_mounts()
    assert any("/context," in m for m in mounts)
    assert not any("/improvement" in m for m in mounts)


async def test_main_provider_route_cap_is_applied_without_modifying_worker(tmp_path):
    from dataclasses import replace

    from roami_agent.protocol.model_routes import settings_with_route

    settings = Settings(endpoint="http://localhost/v1", model="main", worker_model="worker")
    route = replace(settings.route("main"), parameters={"max_tokens": 64}, max_retries=0)
    value = settings_with_route(settings, "main", route)
    assert value.route("main").parameters == {"max_tokens": 64}
    assert value.route("main").max_retries == 0
    assert settings.route("main").max_retries == 2
    worker = settings_with_route(
        settings, "worker", replace(settings.route("worker"), parameters={"max_tokens": 32})
    )
    assert worker.route("main") == settings.route("main")
    assert worker.route("worker").parameters == {"max_tokens": 32}


async def test_uncontrolled_cache_cannot_be_relabeled_by_browser_registration(tmp_path):
    control = ImprovementControl(Ledger(tmp_path / "ledger.sqlite3"))
    with pytest.raises(DomainError, match="CACHE_ATTESTATION"):
        control.register_machine(
            "owner", {"id": "machine", "label": "M", "mode": "container", "cache_mode": "cold"}
        )
    with pytest.raises(DomainError, match="MACHINE_MODE"):
        control.register_machine(
            "owner",
            {
                "id": "machine",
                "label": "M",
                "mode": "container",
                "cache_mode": "cold",
                "cache_attestation": "Operator verified isolated cache",
            },
            local_only=True,
        )
    control.register_machine(
        "owner",
        {
            "id": "machine",
            "label": "M",
            "mode": "container",
            "cache_mode": "cold",
            "cache_attestation": "Operator verified isolated cache",
        },
    )


async def test_observation_requires_semantic_review_and_rolls_back_regression(tmp_path):
    w, cfg, clock, repo, _cycle = await setup(tmp_path)
    w.discover()
    review = w.claim()
    await observe_cycle(
        w, review, Settings(), cfg, provider_factory=lambda _: Reviewer(finding=True)
    )
    complete_review_fixture(w, review, {"done": True})
    repair = w.claim()
    revisions = SourceRevisions(w.ledger.path.parent / "source")
    candidate = await revisions.repair(
        w, repair, Settings(), cfg, provider_factory=lambda _: Reviewer()
    )
    w.complete(repair, candidate, next_kind="verify", item_state="verifying")
    verify = w.claim()
    evidence = await verify_candidate(
        w, verify, Settings(), cfg, executor_factory=FixtureCodeExecutor
    )
    w.complete(verify, evidence, next_kind="activate", item_state="ready")
    activate = w.claim()
    release = await activate_code(w, activate, revisions, cfg)
    w.complete(activate, release, item_state="observing")
    clock.next_day()

    class Regression(FixtureCodeExecutor):
        async def run_arm(self, arm, case, policy, root):
            result = await super().run_arm(arm, case, policy, root)
            if arm == "candidate" and case["id"] == "CODE-01":
                result["grade"] = {"quality": 0, "passed": False, "pending": False}
                result["verified_delivery"] = False
            return result

    result = await run_cycle(
        ledger=w.ledger,
        owner="owner",
        day=w.day("owner"),
        suite=make_suite(),
        machine=MACHINE,
        executor=Regression(Settings(), candidate),
        baseline={},
        candidate={},
        output_root=w.ledger.path.parent / "runs",
        daily_tokens=20000000,
        daily_episodes=1000,
        source_builds={arm: candidate[arm + "_build_hash"] for arm in ("baseline", "candidate")},
    )
    assert observe_code(w, "owner", result["cycle_id"])["reason"] == "semantic_review_incomplete"
    assert active_code(w, "owner") is not None
    w.discover()
    review = w.claim()
    await observe_cycle(w, review, Settings(), cfg, provider_factory=lambda _: Reviewer())
    observed = observe_code(w, "owner", result["cycle_id"])
    assert observed["state"] == "reopened" and observed["rollback"]
    assert active_code(w, "owner") is None
    complete_review_fixture(w, review, {"done": True})
    next_step = w.claim()
    assert next_step["kind"] == "repair" and next_step["payload"]["attempt"] == 2
    assert (repo / SOURCE).read_text() == "VALUE = 1\n"


async def test_source_alias_cannot_expose_protected_evaluator_to_repair_model(tmp_path):
    w, cfg, _, repo, _ = await setup(tmp_path)
    oracle = repo / "agent-runtime/src/roami_agent/improvement/oracle.py"
    oracle.parent.mkdir()
    oracle.write_text("PRIVATE_FIXTURE = 7\n")
    (repo / "agent-runtime/src/roami_agent/context/alias").symlink_to(
        "../improvement", target_is_directory=True
    )
    await git(repo, "add", ".")
    await git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@localhost",
        "commit",
        "-qm",
        "source alias fixture",
    )
    cfg = w.configure(
        "owner", {**cfg, "base_commit": (await git(repo, "rev-parse", "HEAD")).strip()}
    )
    w.discover()
    review = w.claim()
    finding = {
        "mechanism": "alias",
        "fact": "fixture",
        "paths": ["agent-runtime/src/roami_agent/context/alias/oracle.py"],
    }
    w.record_findings(review, [finding])
    seed_review_for_stage_fixture(w, review)
    complete_review_fixture(w, review, {"done": True})
    repair = w.claim()
    provider = Reviewer()
    with pytest.raises(DomainError, match="SOURCE_CONTEXT_REQUIRED"):
        await SourceRevisions(w.ledger.path.parent / "source").repair(
            w, repair, Settings(), cfg, provider_factory=lambda _: provider
        )
    assert provider.calls == 0


async def test_single_baseline_semantic_review_finishes_all_sixty_before_repair(tmp_path):
    w, cfg, _clock, _repo, cycle = await setup(tmp_path, paired=False)
    w.discover()
    action = w.claim()
    provider = Reviewer(finding=True)
    summary = await observe_cycle(w, action, Settings(), cfg, provider_factory=lambda _: provider)
    assert summary["semantic_reviewed"] == 60 and provider.calls == 61
    saved = w.review_saved("owner", cycle["cycle_id"])
    assert len(saved) == 60
    missing, original = next(iter(saved.items()))
    with w.ledger.connection() as db:
        db.execute(
            "DELETE FROM rsi_semantic_reviews WHERE owner=? AND cycle_id=? AND trial_key=?",
            ("owner", cycle["cycle_id"], missing),
        )
    with pytest.raises(DomainError, match="REVIEW_INCOMPLETE"):
        w.complete(action, summary)
    assert not w.ledger.get("owner", cycle["cycle_id"])["report"]["daily_complete"]
    w.save_review("owner", cycle["cycle_id"], missing, original)
    complete_review_fixture(w, action, summary)
    assert w.ledger.get("owner", cycle["cycle_id"])["report"]["daily_complete"]
    assert len(w.snapshot("owner")["improvements"]) == 1
    assert w.claim()["kind"] == "repair"
