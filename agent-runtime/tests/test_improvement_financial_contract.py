"""Financial result contracts accept requested fields and reject unsupported claims."""

import copy
import json

import pytest

from roami_agent.improvement.authored_grading import grade_authored
from roami_agent.improvement.corpus import authored_suite
from roami_agent.improvement.executors import materialize


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "string_scenarios",
        "missing_scenarios",
        "one_scenario",
        "empty_condition",
        "missing_falsification",
        "empty_falsification",
        "extra_claim",
        "invented_price",
        "changed_receipt",
        "wrong_type",
    ],
)
async def test_requested_scenarios_are_validated_separately_from_fixed_facts(tmp_path, fault):
    case = next(c for c in authored_suite("stock-contract")["cases"] if c["id"] == "STOCK-03")
    workspace = tmp_path / "work"
    materialize(case, workspace)
    value = {
        **copy.deepcopy(case["judge"]["expected"]),
        "scenarios": [
            {"condition": "Confirmed orders", "direction": "conditional improvement"},
            {"condition": "Delayed orders", "direction": "conditional pressure"},
        ],
        "falsification": ["No matching revenue in the next disclosure"],
    }
    if fault == "string_scenarios":
        value["scenarios"] = ["Orders confirmed", "Orders delayed"]
        value["falsification"] = "No matching revenue"
    elif fault == "missing_scenarios":
        del value["scenarios"]
    elif fault == "one_scenario":
        value["scenarios"].pop()
    elif fault == "empty_condition":
        value["scenarios"][0]["condition"] = " "
    elif fault == "missing_falsification":
        del value["falsification"]
    elif fault == "empty_falsification":
        value["falsification"] = [""]
    elif fault == "extra_claim":
        value["investment_advice"] = "Guaranteed profit"
    elif fault == "invented_price":
        value["target_price"] = 100
    elif fault == "changed_receipt":
        value["receipt"] = "invented"
    elif fault == "wrong_type":
        value = []
    (workspace / "result.json").write_text(json.dumps(value))
    (workspace / "report.md").write_text(
        "情景与反证基于 market.json；" * 6 + case["fixture_receipt"]
    )
    grade = await grade_authored(case, workspace, None)
    assert grade["passed"] is (fault in {None, "string_scenarios"})


@pytest.mark.parametrize("fault", [None, "future_source", "source_text", "wrong_classification"])
async def test_fact_and_commentary_arrays_use_as_of_source_ids(tmp_path, fault):
    case = next(c for c in authored_suite("stock-contract")["cases"] if c["id"] == "STOCK-01")
    assert '"facts": ["source.id"]' in case["prompt"]
    assert '"commentary": ["source.id"]' in case["prompt"]
    assert '"contract":' not in case["prompt"]
    assert "执行要求（不是结果字段）" in case["prompt"]
    workspace = tmp_path / "work"
    materialize(case, workspace)
    value = copy.deepcopy(case["judge"]["expected"])
    if fault == "future_source":
        value["facts"].append("future")
    elif fault == "source_text":
        value["facts"] = ["产品已发布"]
    elif fault == "wrong_classification":
        value["facts"], value["commentary"] = value["commentary"], value["facts"]
    (workspace / "result.json").write_text(json.dumps(value))
    (workspace / "report.md").write_text("Source: market.json. " * 4 + case["fixture_receipt"])
    assert (await grade_authored(case, workspace, None))["passed"] is (fault is None)
