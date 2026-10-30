import asyncio
import json

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.domain.policy import policy_id, validate_policy
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.integrations.source_identity import implementation_hash
from roami_agent.improvement.persistence.control import ImprovementControl
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.persistence.releases import Releases
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.improvement import policy_binding
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.server.model_settings import RuntimeSettings


def suite_file(tmp_path):
    suite = freeze_suite(
        "data",
        [
            {
                "id": "a",
                "category": "DATA",
                "layer": "authored_real",
                "split": "development",
                "prompt": "Return 2",
                "counts_as_delivery": True,
                "files": {},
                "limits": {"seconds": 10, "tokens": 10000, "requests": 2},
                "judge": {"kind": "numeric", "expected": 2},
            }
        ],
    )
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite))
    return path


def control(tmp_path):
    c = ImprovementControl(Ledger(tmp_path / "ledger.sqlite3"))
    c.register_machine("local", {"id": "a", "label": "A", "mode": "native_files"}, local_only=True)
    c.register_suite("local", suite_file(tmp_path))
    prefs = c.preferences("local")
    return c, {
        **prefs,
        "suite_id": "data",
        "machine_ids": ["a"],
        "daily_tokens": 100000,
        "daily_episodes": 10,
    }


def test_opt_in_and_frozen_request_survive_settings_edits(tmp_path):
    c, settings = control(tmp_path)
    assert not c.preferences("local")["enabled"]
    c.save("local", settings)
    first = c.enqueue("local", machine_id="a", request_key="one")
    assert first == c.enqueue("local", machine_id="a", request_key="one")
    current = c.preferences("local")
    c.save("local", {**current, "daily_tokens": 200000})
    request = c.claim()
    assert "daily_tokens" not in c.profiles(request)[0]
    assert c.cancel("local", request["id"])["state"] == "cancelling"
    c.finish(request, "interrupted")
    assert c.requests("local")[0]["state"] == "interrupted"
    assert c.requests("other") == []
    with pytest.raises(DomainError, match="SETTINGS_CONFLICT"):
        c.save("local", settings)


def test_formal_suite_and_remote_command_boundaries_remain_without_token_budgets(tmp_path):
    c, settings = control(tmp_path)
    with pytest.raises(DomainError, match="FORMAL_SUITE_INCOMPLETE"):
        c.save("local", {**settings, "enabled": True, "daily_tokens": 0})
    with pytest.raises(DomainError, match="MACHINE_MODE"):
        c.register_machine(
            "local",
            {"id": "x", "label": "x", "mode": "external", "argv": ["/bin/sh"]},
            local_only=True,
        )


def seed_evidence(ledger, *, broken=False):
    baseline, candidate = validate_policy({}), validate_policy({"memory_recall_tokens": 1500})
    manifest = {
        "machine": {"id": "x"},
        "reserved_tokens": 100000,
        "reserved_episodes": 108,
        "baseline_id": policy_id(baseline),
        "candidate_id": policy_id(candidate),
        "baseline_policy": baseline,
        "candidate_policy": candidate,
        "implementation_hash": implementation_hash(),
        "standard_version": "v1",
    }
    cycle, _ = ledger.reserve(
        "local", "2026-10-23", manifest, tokens_limit=100000, episodes_limit=108
    )
    for arm in ("baseline", "candidate"):
        for i in range(54):
            failed = broken and arm == "candidate" and i == 0
            trial = {
                "case_id": str(i),
                "case_hash": digest(i),
                "cluster": str(i),
                "category": "DATA",
                "layer": "authored_real",
                "split": "holdout" if i < 30 else "validation",
                "machine_hash": "machine",
                "model_hash": "model",
                "cache_mode": "cold",
                "policy_id": manifest[arm + "_id"],
                "grade": {"passed": not failed, "quality": 0 if failed else 80, "pending": False},
                "verified_delivery": not failed,
                "release_blockers": [],
                "metrics": {"tokens": 100 if arm == "baseline" else 80, "elapsed_ms": 100},
            }
            ledger.append("local", cycle, arm, trial)
    ledger.finish("local", cycle, {"comparison": {"eligible_for_promotion": True}})
    return cycle


def test_release_recomputes_gate_and_never_trusts_executor_success(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    cycle = seed_evidence(ledger, broken=True)
    with pytest.raises(DomainError, match="PROMOTION_REJECTED"):
        Releases(ledger).publish("local", [cycle], expected_seq=0, request_key="release")


def test_binding_is_per_conversation_and_rollback_does_not_mutate_it(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    cycle = seed_evidence(ledger)
    releases = Releases(ledger)
    old = releases.bind("local", "old", 1, validate_policy({}))
    result = releases.publish("local", [cycle], expected_seq=0, request_key="release")
    fresh = releases.bind("local", "new", result["created_ms"] + 1, validate_policy({}))
    assert old["release_id"] is None and fresh["policy"]["memory_recall_tokens"] == 1500
    with pytest.raises(DomainError, match="REVISION_CONFLICT"):
        releases.rollback("local", expected_seq=0, request_key="stale")
    rollback = releases.rollback("local", expected_seq=result["seq"], request_key="rollback")
    assert releases.bind("local", "new", 9, validate_policy({})) == fresh
    restored = releases.bind("local", "later", rollback["created_ms"] + 1, validate_policy({}))
    assert restored["release_id"] is None and restored["policy"]["memory_recall_tokens"] == 2000
    assert releases.list("other")["active"] is None


async def test_simultaneous_policy_contexts_do_not_change_global_settings():
    settings = RuntimeSettings(Settings())

    async def bound(limit):
        token = policy_binding.set({"policy": {"memory_recall_limit": limit}})
        try:
            await asyncio.sleep(0)
            return settings.memory_recall_limit
        finally:
            policy_binding.reset(token)

    assert await asyncio.gather(bound(2), bound(12)) == [2, 12]
    assert settings.memory_recall_limit == 8


async def test_mutating_http_endpoints_enforce_owner_and_request_shape(store):
    class Model:
        model = "fixture"

    runtime = Runtime(store, Model(), development_rsi=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://runtime",
    ) as client:
        request = {"id": "a", "label": "A", "mode": "native_files"}
        response = await client.post(
            "/v1/improvement/machines", json=request, headers={"X-Roami-Owner": "other"}
        )
        assert response.status_code == 403
        assert (
            await client.post(
                "/v1/improvement/machines", json=request, headers={"X-Roami-Owner": "local"}
            )
        ).status_code == 200
        response = await client.get("/v1/improvement", headers={"X-Roami-Owner": "local"})
        assert response.json()["data"]["catalog"]["machines"][0]["id"] == "a"


def test_daily_settings_normalize_old_sample_limit_and_reject_unfinished_formal_suite(tmp_path):
    c, settings = control(tmp_path)
    assert settings["cases_per_day"] == 60
    with c.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_preferences VALUES(?,?,?,?)",
            ("local", 1, json.dumps({"cases_per_day": 4}), 1),
        )
    assert c.preferences("local")["cases_per_day"] == 60
    with pytest.raises(DomainError, match="FORMAL_SUITE_INCOMPLETE"):
        c.save("local", {**settings, "revision": 1, "enabled": True})
    with pytest.raises(DomainError, match="FULL_SUITE_REQUIRED"):
        c.save("local", {**settings, "revision": 1, "cases_per_day": 4})


def test_release_requires_actual_log_reviews_instead_of_report_completion_flag(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    cycle = seed_evidence(ledger)
    record = ledger.get("local", cycle)
    manifest = {
        **record["manifest"],
        "review_required": True,
        "case_ids": [str(i) for i in range(54)],
    }
    with ledger.connection() as db:
        db.execute(
            "UPDATE rsi_cycles SET manifest_json=?,report_json=? WHERE id=?",
            (
                json.dumps(manifest),
                json.dumps({"daily_complete": True, "review": {"complete": True}}),
                cycle,
            ),
        )
    with pytest.raises(DomainError, match="REVIEW_INCOMPLETE"):
        Releases(ledger).publish("local", [cycle], expected_seq=0, request_key="release")


async def test_no_new_candidate_still_runs_the_full_daily_suite(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from roami_agent.improvement.evaluation.corpus import authored_suite
    from roami_agent.improvement.evaluation.daily_suite import PUBLIC_QUOTAS, assemble_daily
    from roami_agent.improvement.workflows.worker import EvaluationWorker

    c, settings = control(tmp_path)
    case = json.loads(suite_file(tmp_path).read_text())["cases"][0]
    public = freeze_suite(
        "public",
        [
            {
                **case,
                "id": f"{name}:{i}",
                "layer": "public_component",
                "split": "public_test",
                "origin": {
                    "benchmark": name,
                    "task_id": str(i),
                    "revision": "a" * 40,
                    "input_sha256": digest([name, i]),
                    "source_split": "test",
                    "adapter_revision": "fixture-only",
                },
            }
            for name, count in PUBLIC_QUOTAS.items()
            for i in range(count)
        ],
    )
    full = assemble_daily("full", [authored_suite("fixture-only"), public])
    path = tmp_path / "full.json"
    path.write_text(json.dumps(full))
    c.register_suite("local", path)
    c.save("local", {**settings, "suite_id": "full", "enabled": True})
    c.enqueue("local", machine_id="a", request_key="daily", kind="daily")
    ran = {}

    async def run(**arguments):
        ran.update(arguments)
        return {"cycle_id": "proof", "full_suite_complete": True}

    monkeypatch.setattr("roami_agent.improvement.workflows.worker.next_candidate", lambda *_: None)
    monkeypatch.setattr("roami_agent.improvement.workflows.cycle.run_cycle", run)
    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            current=Settings(endpoint="http://evaluation.invalid/v1", model="fixture")
        )
    )
    from roami_agent.improvement.persistence.research_repository import ResearchRepository

    service = SimpleNamespace(
        control=c, ledger=c.ledger, wakeup=asyncio.Event(), research=ResearchRepository(c.ledger)
    )
    await EvaluationWorker(runtime, service).execute(c.claim())
    assert len(ran["suite"]["cases"]) == 60
    assert ran["baseline"] == ran["candidate"]
    assert ran["paired"] is False
    assert c.requests("local")[0]["state"] == "completed"


def test_baseline_stability_noise_cannot_publish_an_unchanged_policy(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    cycle = seed_evidence(ledger)
    manifest = ledger.get("local", cycle)["manifest"]
    manifest.update(
        candidate_id=manifest["baseline_id"], candidate_policy=manifest["baseline_policy"]
    )
    with ledger.connection() as db:
        db.execute(
            "UPDATE rsi_cycles SET manifest_json=? WHERE id=?", (json.dumps(manifest), cycle)
        )
        db.execute(
            "UPDATE rsi_trials SET record_json=json_set(record_json,'$.policy_id',?) WHERE cycle_id=?",
            (manifest["baseline_id"], cycle),
        )
    with pytest.raises(DomainError, match="PROMOTION_REJECTED"):
        Releases(ledger).publish("local", [cycle], expected_seq=0, request_key="noise")
