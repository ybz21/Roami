"""Frozen executable regression variants for the twenty decision-space contracts."""

import ast
import json
import time
from pathlib import Path

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality

NODES = {
    "MG01": [
        ("automatic_memory", "remember_request_persists_before_reply_and_is_idempotent"),
        ("automatic_memory", "questions_negations_and_examples_do_not_activate"),
    ],
    "MG02": [
        (
            "automatic_memory",
            "forgetting_user_preference_excludes_other_records_of_original_source",
        ),
        (
            "memory_pipeline",
            "ordinary_delete_invalidates_derived_memories_but_forget_tracks_prompt_dependencies",
        ),
    ],
    "MR01": [
        ("persistence", "cjk_memory_scope_version_and_forgetting"),
        ("memory_pipeline", "retrieval_literal_or_scope_validity_and_bounded_character_fallback"),
    ],
    "MR02": [
        ("automatic_memory", "late_automatic_preference_cannot_override_newer_user_source"),
        ("answer_delivery", "actual_user_language_and_explicit_override_are_distinct"),
    ],
    "CT01": [
        ("context_provider", "compaction_persists_summary_preserves_transcript_and_appends"),
        ("context_provider", "context_of_turn_does_not_include_later_user_messages"),
    ],
    "CT02": [
        (
            "native_workspace",
            "native_task_carries_original_attachment_and_honors_artifact_deletion",
        ),
        ("task_continuation_affinity", "followup_preserves_task_provider_and_session"),
    ],
    "TL01": [("foundations", "tool_list_lists_categories_pages_and_removes_old_entry")],
    "TL02": [
        ("foundations", "malformed_cli_arguments_have_an_executable_recovery_example"),
        ("argument_repair_progress", "changing_schema_issues_and_parallel_calls_can_be_repaired"),
    ],
    "TE01": [
        (
            "coordinator_handoff",
            "read_then_two_handoffs_in_one_batch_end_without_extra_model_round",
        ),
        ("foundations", "bash_cli_records_actual_read_effect_and_timeline"),
    ],
    "TE02": [
        ("persistence", "recovery_marks_partial_and_unknown_tools"),
        ("task_delivery_benchmark", "B05_unknown_outcome_blocks_new_launch_immediately"),
    ],
    "TR01": [
        (
            "native_workspace",
            "long_native_result_keeps_full_source_and_bounded_completion_evidence",
        ),
        (
            "answer_delivery",
            "large_requested_debug_answer_is_delivered_whole_without_externalization",
        ),
    ],
    "TR02": [
        ("routing_policy", "external_or_invented_quote_cannot_override_the_user"),
        ("foundations", "background_roles_share_workspace_and_registered_cli_rules"),
    ],
    "SK01": [
        ("skill_references", "reference_is_loaded_on_demand_and_changes_catalog_version"),
        ("foundations", "search_skill_loading_and_disable_policy"),
    ],
    "SK02": [
        ("skill_references", "reference_is_loaded_on_demand_and_changes_catalog_version"),
        ("skill_references", "reference_cannot_escape_skill"),
        ("document_capability_policy", "native_intake_obeys_execution_capability_policy"),
        (
            "document_capability_policy",
            "next_worker_prompt_drops_input_or_workflow_after_policy_changes",
        ),
        (
            "document_capability_policy",
            "intake_stops_remaining_reads_when_policy_changes_during_io",
        ),
    ],
    "PL01": [
        ("execution_traces", "trace_joins_native_task_and_completion_without_another_user_turn"),
        ("native_workspace", "created_file_is_delivered_even_when_worker_and_main_omit_links"),
        (
            "assignment_recovery",
            "untracked_user_executor_is_explained_and_cannot_be_hidden_in_native_wrapper",
        ),
        (
            "routing_policy",
            "new_professional_executor_and_model_reach_the_accepted_task",
        ),
    ],
    "PL02": [
        (
            "coordinator_handoff",
            "read_then_two_handoffs_in_one_batch_end_without_extra_model_round",
        ),
        ("task_delivery_benchmark", "B07_independent_tasks_in_one_request_are_allowed"),
    ],
    "MB01": [
        ("runtime", "runtime_streams_committed_reply_and_usage"),
        ("generation_parameters", "invalid_parameters_fail_before_any_provider_request"),
    ],
    "MB02": [
        (
            "gateway_quota_authority",
            "go_quota_rejection_remains_authoritative_even_with_zero_python_limits",
        ),
        ("improvement", "missing_or_partial_retry_usage_stays_unknown_without_local_quota"),
        ("improvement", "episode_budget_counts_all_models_and_does_not_double_count_cache"),
    ],
    "VD01": [
        ("task_delivery_benchmark", "B24_missing_output_is_reported_without_changing_task_state"),
        ("native_workspace", "created_file_is_delivered_even_when_worker_and_main_omit_links"),
    ],
    "VD02": [
        ("task_cancellation", "cancel_with_unknown_own_stop_never_claims_confirmed_cancelled"),
        ("task_cancellation", "shutdown_during_verification_rechecks_evidence_after_restart"),
    ],
}


def nodes(case_id):
    key = case_id.removeprefix("MECH-")
    require(key in NODES, "RSI_REGRESSION_PACK_REQUIRED")
    return [f"test_{module}.py::test_{name}" for module, name in NODES[key]]


def regression_program(policy, selectors):
    return """import json,pytest
from roami_agent.protocol.improvement import policy_binding
policy_binding.set({{"policy":json.loads({!r})}})
class Receipt:
 def __init__(self):self.selectors=[];self.collected=0;self.passed=0;self.skipped=0
 def pytest_collection_finish(self,session):
  self.collected=len(session.items)
  self.selectors=sorted(set(item.nodeid.split('[',1)[0] for item in session.items))
 def pytest_runtest_logreport(self,report):
  uncertain=report.skipped or bool(getattr(report,'wasxfail',None))
  if uncertain:self.skipped+=1
  if report.when=='call' and report.passed and not uncertain:self.passed+=1
receipt=Receipt()
result=pytest.main([{},"-q","--asyncio-mode=auto","--rootdir=/testing","-p","no:cacheprovider","--basetemp=/tmp/rsi-tests"],plugins=[receipt])
print(json.dumps({{"exit_code":int(result),"selectors":receipt.selectors,"collected":receipt.collected,"passed":receipt.passed,"skipped":receipt.skipped}}))
""".format(json.dumps(policy), ",".join(repr("/testing/" + s) for s in selectors))


def regression_passed(result, selectors):
    return (
        result.get("exit_code") == 0
        and result.get("skipped") == 0
        and result.get("passed", 0) > 0
        and result.get("passed") == result.get("collected")
        and set(result.get("selectors", [])) == set(selectors)
    )


async def run_mechanism(case, policy, root, executor):
    from roami_agent.improvement.evaluation.execution.containers import docker_command

    tests = (
        Path(executor.regression_root)
        if getattr(executor, "regression_root", None)
        else Path(__file__).parents[4] / "tests"
    )
    require(tests.is_dir(), "RSI_REGRESSION_PACK_REQUIRED")
    selectors = nodes(case["id"])
    require(case["judge"].get("selectors") == selectors, "RSI_REGRESSION_PACK_CHANGED")
    require(
        all((tests / n.split("::")[0]).is_file() for n in selectors), "RSI_REGRESSION_PACK_REQUIRED"
    )
    for selector in selectors:
        module, name = selector.split("::")
        functions = {
            node.name
            for node in ast.parse((tests / module).read_text()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        require(name in functions, "RSI_REGRESSION_NODE_REQUIRED")
    program = regression_program(policy, selectors)
    started = time.monotonic()
    name = "roami-rsi-mechanism-" + digest([str(root), policy])[:20]
    await docker_command(
        "create",
        "--name",
        name,
        "--label",
        "roami.rsi=" + name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{__import__('os').getuid()}:{__import__('os').getgid()}",
        "--memory",
        "2g",
        "--pids-limit",
        "256",
        "--tmpfs",
        "/tmp:rw,size=536870912,mode=1777",
        "--mount",
        f"type=bind,src={tests},dst=/testing,readonly",
        *executor.source_mounts(),
        "--entrypoint",
        "python",
        executor.image_id,
        "-c",
        program,
    )
    try:
        raw = await docker_command("start", "--attach", name, timeout=case["limits"]["seconds"])
        result = json.loads(raw.decode().splitlines()[-1])
        passed = regression_passed(result, selectors)
    finally:
        await executor.remove(name, name)
    (root / "regression.log").write_bytes(raw)
    grade = quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed)
    grade.update(
        grade_scope="deterministic_mechanism_regression",
        selectors=selectors,
        regression_receipt=result,
        evidence_hash=digest(raw.decode()),
    )
    return {
        "grade": grade,
        "metrics": {
            "tokens": 0,
            "model_calls": 0,
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "cost_scope": "regression_harness_not_agent_episode",
            "right_censored": not passed,
        },
        "verified_delivery": False,
        "release_blockers": [],
        "execution_kind": "runtime_regression_variant",
    }
