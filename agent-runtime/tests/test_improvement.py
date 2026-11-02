import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.improvement.domain.comparison import compare
from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.domain.policy import (
    apply_policy,
    next_candidate,
    policy_id,
    propose,
    validate_policy,
)
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import agent_view, freeze_suite, validate_suite
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.executors import (
    ExternalExecutor,
    NativeFilesExecutor,
)
from roami_agent.improvement.evaluation.grading import calibrated_grade, judge_case
from roami_agent.improvement.evaluation.sampling import import_finqa
from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.improvement.workflows.cycle import daily_selection, run_cycle
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app


def case(identifier="test-1", **overrides):
    return {
        "id": identifier,
        "category": "DATA",
        "layer": "authored_real",
        "split": "development",
        "prompt": "Read input.json and save the sum as output.json.",
        "counts_as_delivery": True,
        "files": {"input.json": "[17,23]"},
        "limits": {"seconds": 5, "tokens": 128000, "requests": 8},
        "judge": {"kind": "json", "path": "output.json", "expected": {"sum": 40}},
        **overrides,
    }


def fixture_case(identifier="test-1", **overrides):
    return case(
        identifier,
        protocol_script=[
            {"tool": {"name": "read", "args": {"path": "$WORKSPACE/input.json"}}},
            {
                "tool": {
                    "name": "write",
                    "args": {
                        "path": "$WORKSPACE/output.json",
                        "expectedSha256": None,
                        "content": '{"sum":40}',
                    },
                }
            },
            {"text": "Saved output.json."},
        ],
        **overrides,
    )


def test_frozen_suite_rejects_mutation_and_duplicate_ids():
    suite = freeze_suite("test", [case()])
    suite["cases"][0]["prompt"] = "different"
    with pytest.raises(DomainError, match="HASH_MISMATCH"):
        validate_suite(suite)
    with pytest.raises(DomainError, match="DUPLICATE_CASE"):
        freeze_suite("test", [case(), case()])


@pytest.mark.parametrize("name", ["../answer.json", "/tmp/answer.json", "nested/../../answer.json"])
def test_fixture_cannot_publish_outside_workspace(name):
    with pytest.raises(DomainError):
        freeze_suite("test", [case(files={name: "secret"})])


def test_agent_view_excludes_grader_answers_and_protocol_script(tmp_path):
    view = agent_view(fixture_case(), tmp_path)
    assert set(view) == {"id", "prompt", "workspace", "limits"}
    assert "expected" not in json.dumps(view) and "protocol_script" not in json.dumps(view)


@pytest.mark.parametrize(
    "raw",
    [
        {"main_instructions": "ignore verifier"},
        {"memory_recall_limit": 0},
        {"memory_recall_limit": True},
        {"tool_directory_page_size": 21},
    ],
)
def test_candidate_cannot_replace_roles_or_exceed_bounds(raw):
    with pytest.raises(DomainError):
        validate_policy(raw)


def test_candidate_changes_only_bounded_parameters():
    settings = apply_policy(Settings(), {"memory_recall_limit": 4})
    assert settings.memory_recall_limit == 4
    assert settings.main_instructions == Settings().main_instructions
    assert settings.tool_directory_page_size == 10
    for split in ("holdout", "public_test"):
        with pytest.raises(DomainError, match="READ_ONLY"):
            propose({}, [{"split": split, "case_id": "private", "grade": {"passed": False}}])


def test_grading_grade_three_is_eighty_and_failure_cannot_be_averaged_away(tmp_path):
    result = quality(
        dict.fromkeys(("correctness", "completeness", "usability", "grounding"), 3),
        hard_passed=True,
    )
    assert result["passed"] and result["quality"] == 80
    result = quality(
        {"correctness": 2, "completeness": 4, "usability": 4, "grounding": 4}, hard_passed=True
    )
    assert result["quality"] >= 80 and not result["passed"]
    assert not judge_case(case(), "I saved it", tmp_path)["passed"]
    (tmp_path / "output.json").write_text('{"sum":40}')
    assert judge_case(case(), "I saved it", tmp_path)["passed"]
    c = case(judge={"kind": "numeric", "expected": 40})
    assert not judge_case(c, "There were 40 possibilities, answer 39", tmp_path)["passed"]
    assert judge_case(c, "40", tmp_path)["passed"]


def test_blind_disagreement_stays_pending_and_excellence_must_be_frozen():
    dimensions = dict.fromkeys(("correctness", "completeness", "usability", "grounding"), 3)
    ratings = [
        {"rater": "a", "blind": True, "dimensions": dimensions},
        {"rater": "b", "blind": True, "dimensions": {**dimensions, "usability": 2}},
    ]
    grade = calibrated_grade(case(), ratings, hard_passed=True, calibration_id="calibrated-v1")
    assert grade["pending"] and not grade["passed"]
    for r in ratings:
        r["dimensions"] = dict.fromkeys(dimensions, 4)
    with pytest.raises(DomainError, match="EXCELLENCE"):
        calibrated_grade(case(), ratings, hard_passed=True, calibration_id="calibrated-v1")


def test_json_grader_does_not_treat_boolean_as_a_number(tmp_path):
    c = case(judge={"kind": "json", "expected": {"nested": [1]}})
    assert not judge_case(c, '{"nested":[true]}', tmp_path)["passed"]
    assert judge_case(c, '{"nested":[1.0]}', tmp_path)["passed"]


class UsageModel:
    model = "test"

    def __init__(self, usage):
        self.usage = usage

    async def stream(self, messages, tools):
        yield ModelEvent("text", "answer")
        if self.usage:
            yield ModelEvent("usage", self.usage)


async def consume(model):
    return [event async for event in model.stream([{"role": "user", "content": "hello"}], [])]


async def test_episode_budget_counts_all_models_and_does_not_double_count_cache():
    budget = EpisodeBudget({"seconds": 10, "tokens": 20000, "requests": 2})
    usage = {
        "inputTokens": 100,
        "outputTokens": 20,
        "cacheReadTokens": 80,
        "requestAttempts": 1,
        "retryUsageKnown": True,
    }
    await asyncio.gather(
        consume(MeteredModel(UsageModel(usage), budget, "main")),
        consume(MeteredModel(UsageModel(usage), budget, "memory")),
    )
    assert budget.metrics()["tokens"] == 240
    await consume(MeteredModel(UsageModel(usage), budget, "worker"))
    assert budget.metrics()["tokens"] == 360


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"inputTokens": 100, "outputTokens": 20, "requestAttempts": 2, "retryUsageKnown": False},
    ],
)
async def test_missing_or_partial_retry_usage_stays_unknown_without_local_quota(usage):
    budget = EpisodeBudget({"seconds": 10, "tokens": 10000, "requests": 5})
    await consume(MeteredModel(UsageModel(usage), budget, "main"))
    assert budget.metrics()["tokens"] is None
    await consume(MeteredModel(UsageModel(usage), budget, "worker"))
    assert budget.metrics()["tokens"] is None and budget.metrics()["model_calls"] == 2


def trial(identifier, **overrides):
    return {
        "case_id": identifier,
        "case_hash": digest(identifier),
        "machine_hash": "m",
        "model_hash": "p",
        "cache_mode": "cold",
        "layer": "authored_real",
        "category": "DATA",
        "split": "holdout",
        "cluster": identifier,
        "grade": {"quality": 80, "passed": True, "pending": False},
        "verified_delivery": True,
        "release_blockers": [],
        "metrics": {"tokens": 100, "elapsed_ms": 100},
        **overrides,
    }


def test_fast_failure_does_not_count_as_gain_and_cannot_erase_regression():
    a = [trial(str(i)) for i in range(30)]
    b = copy.deepcopy(a)
    for t in b:
        t["metrics"] = {"tokens": 50, "elapsed_ms": 50}
    b[0].update(grade={"quality": 0, "passed": False}, verified_delivery=False)
    result = compare(a, b)
    assert not result["eligible_for_promotion"]
    assert result["baseline_pass_regressions"] == ["0"]
    assert result["efficiency_pairs"]["tokens"] == 29


def test_unknown_tokens_and_repeated_templates_are_not_release_evidence():
    a = [trial(str(i), cluster="same-template") for i in range(30)]
    b = copy.deepcopy(a)
    for t in b:
        t["metrics"] = {"tokens": None, "elapsed_ms": 50}
    result = compare(a, b)
    assert result["private_holdout_clusters"] == 1
    assert not result["eligible_for_promotion"]
    assert result["paired_success_token_ratio_p50"] is None
    b[0]["model_hash"] = "other-model"
    with pytest.raises(DomainError, match="INCOMPARABLE"):
        compare(a, b)
    with pytest.raises(DomainError, match="UNPAIRED"):
        compare(a, b[:-1])


def test_rotation_does_not_depend_on_input_order_or_observed_scores():
    cases = [case(str(i), category=str(i % 4)) for i in range(20)]
    a = daily_selection(cases, "2026-10-23", limit=4, seed=1)
    b = daily_selection(list(reversed(cases)), "2026-10-23", limit=4, seed=1)
    assert [c["id"] for c in a] == [c["id"] for c in b]
    assert len({c["category"] for c in a}) == 4


def test_public_finance_import_is_pinned_and_does_not_feed_gold_evidence(tmp_path):
    source = [
        {
            "id": str(i),
            "pre_text": ["Report"],
            "post_text": [],
            "table": [["year", "value"]],
            "qa": {
                "question": "What is growth?",
                "answer": str(i + 0.1),
                "exe_ans": i + 0.1,
                "program": "divide(1,2)",
                "gold_inds": {"secret": "oracle"},
                "model_input": ["oracle"],
            },
        }
        for i in range(6)
    ]
    path = tmp_path / "dev.json"
    path.write_text(json.dumps(source))
    a = import_finqa(path, revision="a" * 40, source_split="dev", count=3)
    b = import_finqa(path, revision="a" * 40, source_split="dev", count=3)
    assert a["content_hash"] == b["content_hash"]
    for c in a["cases"]:
        assert "oracle" not in c["prompt"] and "program" not in c["prompt"]
        assert c["origin"]["adapted"] and c["layer"] == "public_component"
        assert len(c["origin"]["input_sha256"]) == 64
    with pytest.raises(DomainError, match="REVISION"):
        import_finqa(path, revision="main", source_split="dev")


def test_atomic_daily_reservation_and_unknown_restart_do_not_replay(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    manifest = {"reserved_tokens": 100, "reserved_episodes": 2, "machine": {"id": "local"}}

    def reserve(_):
        return ledger.reserve("alice", "2026-10-23", manifest, tokens_limit=100, episodes_limit=2)

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(reserve, range(4)))
    assert sum(admitted for _, admitted in receipts) == 1
    identifier = receipts[0][0]
    assert ledger.list("bob") == []
    with pytest.raises(DomainError, match="NOT_FOUND"):
        ledger.get("bob", identifier)
    other, admitted = ledger.reserve(
        "alice",
        "2026-10-23",
        {**manifest, "machine": {"id": "other"}},
        tokens_limit=0,
        episodes_limit=0,
    )
    assert admitted and other != identifier
    with ledger.connection() as db:
        db.execute("UPDATE rsi_cycles SET heartbeat_ms=0")
    assert ledger.recover("alice", stale_seconds=60) == 2
    assert ledger.get("alice", identifier)["state"] == "interrupted"
    assert reserve(0) == (identifier, False)
    assert (tmp_path / "ledger.sqlite3").stat().st_mode & 0o077 == 0


async def test_daily_runs_entire_suite_and_model_free_cases_reserve_no_tokens(tmp_path):
    class RegressionExecutor:
        model_hash = "a" * 64
        reservation_tokens = ContainerExecutor.reservation_tokens

        async def run(self, case, policy, root):
            return {
                "grade": {"passed": True, "quality": 80, "pending": False},
                "metrics": {"tokens": 0, "elapsed_ms": 1},
                "verified_delivery": False,
                "release_blockers": [],
            }

    suite = freeze_suite(
        "mechanisms",
        [
            case(
                "MECH-" + suffix,
                layer="mechanism",
                judge={"kind": "mechanism"},
                counts_as_delivery=False,
            )
            for suffix in ("MG01", "MG02", "MR01", "MR02", "CT01")
        ],
    )
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    report = await run_cycle(
        ledger=ledger,
        owner="local",
        day="2026-10-23",
        suite=suite,
        machine={"id": "local", "cache_mode": "cold", "environment_hash": "a" * 64},
        executor=RegressionExecutor(),
        baseline={},
        candidate={},
        output_root=tmp_path / "runs",
        daily_tokens=1,
        daily_episodes=10,
    )
    detail = ledger.get("local", report["cycle_id"])
    assert len(detail["manifest"]["case_ids"]) == 5
    assert len(detail["trials"]) == 10
    assert detail["manifest"]["reserved_tokens"] == 0
    assert not report["comparison"]["eligible_for_promotion"]


async def test_real_runtime_file_tools_are_graded_and_ledger_repeated_cycle_is_idempotent(tmp_path):
    suite = freeze_suite("runtime-tools", [fixture_case(layer="smoke", counts_as_delivery=False)])
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    arguments = {
        "ledger": ledger,
        "owner": "alice",
        "day": "2026-10-23",
        "suite": suite,
        "machine": {"id": "local", "cache_mode": "cold", "environment_hash": "a" * 64},
        "executor": NativeFilesExecutor(Settings(), fixture=True),
        "baseline": {},
        "candidate": {"memory_recall_limit": 4},
        "output_root": tmp_path / "runs",
        "daily_tokens": 256000,
        "daily_episodes": 2,
    }
    report = await run_cycle(**arguments)
    detail = ledger.get("alice", report["cycle_id"])
    assert report["counts"]["baseline"]["passed"] == report["counts"]["candidate"]["passed"] == 1
    assert report["counts"]["baseline"]["verified_deliveries"] == 0
    assert not report["comparison"]["eligible_for_promotion"]
    assert detail["trials"][0]["execution_kind"] == "protocol_fixture"
    assert detail["trials"][0]["metrics"]["tool_calls"] >= 2
    assert detail["trials"][0]["metrics"]["observed_tokens"] > 0
    assert detail["trials"][0]["metrics"]["tokens"] is None
    assert detail["trials"][0]["metrics"]["token_coverage"] == "partial_deferred_maintenance"
    assert any(r["role"] == "memory" for r in detail["trials"][0]["metrics"]["requests"])
    assert detail["trials"][0]["metrics"]["deferred_maintenance_jobs"] == 1
    assert not (await run_cycle(**arguments))["admitted"]


async def test_improvement_http_is_owner_scoped_and_omits_hidden_trial_content(store):
    runtime = Runtime(store, UsageModel(None), development_rsi=True)
    ledger = runtime.improvement.ledger
    manifest = {"reserved_tokens": 100, "reserved_episodes": 2, "machine": {"id": "local"}}
    identifier, _ = ledger.reserve(
        "alice", "2026-10-23", manifest, tokens_limit=100, episodes_limit=2
    )
    ledger.append(
        "alice", identifier, "baseline", {"case_id": "private", "output": "private oracle content"}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://runtime",
    ) as client:
        endpoint = "/v1/improvement/cycles/" + identifier
        response = await client.get(endpoint, headers={"X-Roami-Owner": "alice"})
        assert response.status_code == 200 and "private oracle content" not in response.text
        assert (await client.get(endpoint, headers={"X-Roami-Owner": "bob"})).status_code == 404
        assert (
            await client.get("/v1/improvement/cycles", headers={"X-Roami-Owner": "bob"})
        ).json()["data"]["cycles"] == []


def test_promotion_requires_validation_and_gain_on_holdout():
    baseline = [trial(str(i), split="holdout" if i < 30 else "validation") for i in range(54)]
    candidate = copy.deepcopy(baseline)
    for t in candidate:
        t["metrics"] = {"tokens": 80, "elapsed_ms": 80}
    assert compare(baseline, candidate)["eligible_for_promotion"]
    for t in candidate[:30]:
        t["metrics"] = {"tokens": 100, "elapsed_ms": 100}
    assert "no_material_gain" in compare(baseline, candidate)["reasons"]
    for t in candidate[:30]:
        t["metrics"] = {"tokens": 80, "elapsed_ms": 80}
    baseline[30]["cluster"] = candidate[30]["cluster"] = baseline[0]["cluster"]
    assert "validation_holdout_cluster_overlap" in compare(baseline, candidate)["reasons"]


def test_next_candidate_keeps_each_coordinate_attributable_and_never_repeats():
    baseline = {"memory_recall_limit": 12, "keep_recent_tokens": 30000}
    first = next_candidate(baseline, [])
    assert first["memory_recall_limit"] == 9 and first["keep_recent_tokens"] == 30000
    proposals = propose(
        first, [{"split": "development", "case_id": "a", "grade": {"passed": True}}]
    )
    report = {"candidate_id": policy_id(first), "proposals": proposals}
    second = next_candidate(baseline, [report])
    assert policy_id(second) != policy_id(first)
    assert len([k for k in first if first[k] != second[k]]) == 1


def test_same_machine_day_is_frozen_even_if_candidate_or_suite_changes(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    manifest = {"machine": {"id": "m"}, "reserved_tokens": 100, "reserved_episodes": 2}
    first, _ = ledger.reserve("a", "2026-10-23", manifest, tokens_limit=1000, episodes_limit=20)
    second, admitted = ledger.reserve(
        "a", "2026-10-23", {**manifest, "policy": "other"}, tokens_limit=1000, episodes_limit=20
    )
    assert second == first and not admitted


def test_conversational_import_preserves_questions_without_reference_answers(tmp_path):
    record = {
        "id": "report/page_1",
        "table": [["items", "17"]],
        "pre_text": [],
        "post_text": [],
        "annotation": {
            "dialogue_break": ["How many items?", "Add 23?"],
            "exe_ans_list": [17, 40],
            "turn_program": ["17", "add(17,23)"],
        },
    }
    path = tmp_path / "conv.json"
    path.write_text(json.dumps([record]))
    suite = import_finqa(path, revision="a" * 40, source_split="dev", count=1, conversational=True)
    c = suite["cases"][0]
    assert len(c["turn_judges"]) == 2
    assert [j["expected"] for j in c["turn_judges"]] == [17, 40]
    assert "40" not in c["followups"][0] and "add(17,23)" not in c["prompt"]


async def test_tool_directory_candidate_changes_default_page_without_hiding_pagination(store):
    from roami_agent.protocol.tools import Tool, object_schema

    runtime = Runtime(
        store, UsageModel(None), settings=apply_policy(Settings(), {"tool_directory_page_size": 2})
    )

    async def empty(args, binding):
        return {}

    for i in range(5):
        runtime.tools.add(
            Tool(
                "fixture_inventory_" + str(i),
                "fixture_inventory",
                object_schema({}),
                empty,
                main=True,
                source="external",
            )
        )
    result = await runtime.tools.invoke(
        {"function": {"name": "tool_list", "arguments": '{"query":"fixture_inventory"}'}},
        "main",
        {},
    )
    assert len(result["items"]) == 2 and result["total"] == 5


async def test_external_worker_receives_only_agent_view_and_unknown_usage_fails(tmp_path):
    import sys

    script = tmp_path / "worker.py"
    script.write_text("""import json,sys
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text())
assert "expected" not in json.dumps(request)
response={"protocol":1,"case_id":request["case"]["id"],"metrics":{"tokens":None,"model_calls":1},"grade":{"hard_passed":True,"pending":False,"native_metric":1}}
Path(request["response_path"]).write_text(json.dumps(response))
""")
    root = tmp_path / "trial"
    root.mkdir()
    executor = ExternalExecutor([sys.executable, str(script)], model_hash="fixed")
    with pytest.raises(DomainError, match="EXTERNAL_USAGE"):
        await executor.run(case(), {}, root)


async def test_interrupted_provider_journal_preserves_error_without_guessing_usage():
    class Interrupted:
        model = "fixture"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "partial")
            raise DomainError("MODEL_STREAM_INCOMPLETE", 502)

    budget = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 2})
    journal = []
    with pytest.raises(DomainError, match="MODEL_STREAM_INCOMPLETE"):
        async for _ in MeteredModel(Interrupted(), budget, "memory", journal=journal).stream(
            [], []
        ):
            pass
    assert journal[0]["error_code"] == "MODEL_STREAM_INCOMPLETE"
    assert journal[0]["events"] == [{"kind": "text", "value": "partial"}]
    assert budget.metrics()["tokens"] is None
    with pytest.raises(DomainError, match="MODEL_STREAM_INCOMPLETE"):
        async for _ in MeteredModel(Interrupted(), budget, "memory").stream([], []):
            pass
    assert len(budget.requests) == 2
