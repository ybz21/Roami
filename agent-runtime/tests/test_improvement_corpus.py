"""Composition and contamination gates for the daily task inventory."""

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.authored_grading import grade_authored
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.corpus import authored_suite
from roami_agent.improvement.evaluation.daily_suite import (
    PUBLIC_QUOTAS,
    assemble_daily,
    daily_coverage,
    validate_private_separation,
)
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.protocol.errors import DomainError


def public_suite():
    cases = []
    for benchmark, count in PUBLIC_QUOTAS.items():
        for i in range(count):
            cases.append(
                {
                    "id": f"{benchmark}:{i}",
                    "category": "PUBLIC_FIXTURE",
                    "layer": "public_component",
                    "split": "development",
                    "cluster": f"{benchmark}:source-{i}",
                    "prompt": f"Fixture only: {benchmark}/{i}",
                    "counts_as_delivery": True,
                    "files": {},
                    "limits": {"seconds": 10, "tokens": 1000, "requests": 1},
                    "judge": {"kind": "numeric", "expected": 1},
                    "origin": {
                        "benchmark": benchmark,
                        "task_id": str(i),
                        "revision": "a" * 40,
                        "source_split": "dev",
                        "input_sha256": digest([benchmark, i]),
                        "adapter_revision": "fixture-only-v1",
                    },
                }
            )
    return freeze_suite("public-fixture", cases)


def test_daily_contract_matches_frozen_design_plan():
    plan = json.loads(
        (
            Path(__file__).parents[2]
            / "docs/design/20261022-roami-agent-rsi/evaluation/sampling-plan.json"
        ).read_text()
    )
    own = authored_suite("fixture-only")
    assert {p["benchmark_id"]: p["target_count"] for p in plan["public_sampling"]} == PUBLIC_QUOTAS
    assert {c["id"] for c in own["cases"]} == set(plan["authored_case_ids"])
    full = assemble_daily("daily-fixture", [own, public_suite()])
    assert daily_coverage(full)["complete"]
    assert full["source_suites"][0]["content_hash"] == own["content_hash"]


@pytest.mark.parametrize(
    "corruption", ["clones", "quota", "upstream_duplicate", "revision", "split", "grader"]
)
def test_sixty_records_cannot_bypass_formal_coverage(corruption):
    full = assemble_daily("full", [authored_suite("fixture-only"), public_suite()])
    cases = copy.deepcopy(full["cases"])
    if corruption == "clones":
        cases = [{**cases[0], "id": str(i)} for i in range(60)]
    elif corruption == "quota":
        cases[-1]["origin"]["benchmark"] = "finqa"
    elif corruption == "upstream_duplicate":
        cases[41]["origin"] = cases[40]["origin"].copy()
    elif corruption == "revision":
        cases[-1]["origin"]["revision"] = "main"
    elif corruption == "split":
        cases[0]["split"] = "holdout"
    else:
        next(c for c in cases if c["layer"] == "mechanism")["judge"] = {
            "kind": "numeric",
            "expected": 1,
        }
    corrupted = freeze_suite("corrupted", cases)
    assert not daily_coverage(corrupted)["complete"]
    with pytest.raises(DomainError, match="FORMAL_SUITE_INCOMPLETE"):
        assemble_daily("rejected", [corrupted])


@pytest.mark.parametrize("overlap", ["identity", "cluster", "inputs"])
def test_hidden_variants_cannot_reuse_daily_identity_cluster_or_exact_inputs(overlap):
    daily = public_suite()
    case = copy.deepcopy(daily["cases"][0])
    case.update(
        id="independent",
        cluster="independent",
        prompt="Independent private task",
        layer="authored_real",
        split="holdout",
    )
    validate_private_separation(daily, freeze_suite("private", [case]))
    if overlap == "identity":
        case["id"] = daily["cases"][0]["id"]
    elif overlap == "cluster":
        case["cluster"] = daily["cases"][0]["cluster"]
    else:
        case["prompt"] = daily["cases"][0]["prompt"]
    with pytest.raises(DomainError, match="PRIVATE_CORPUS_OVERLAP"):
        validate_private_separation(daily, freeze_suite("contaminated", [case]))


class NoSandbox:
    async def sandbox(self, *args, **kwargs):
        raise AssertionError("Invalid frozen inputs must fail before student code runs")


class AnalysisReplay:
    async def sandbox(self, directory, program, **kwargs):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            program.replace('"/workspace"', repr(str(directory))),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), kwargs["timeout"])
            assert process.returncode == 0, stderr.decode()
            return stdout
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


@pytest.mark.parametrize(
    "case_id",
    sorted(c["id"] for c in authored_suite("test")["cases"] if c["layer"] == "authored_real"),
)
async def test_every_authored_case_rejects_missing_deliverables(tmp_path, case_id):
    case = next(c for c in authored_suite("test")["cases"] if c["id"] == case_id)
    tmp_path = tmp_path / "workspace"
    materialize(case, tmp_path)
    grade = await grade_authored(case, tmp_path, NoSandbox())
    assert not grade["hard_passed"] and not grade["passed"]


async def test_financial_output_cannot_rewrite_its_frozen_input(tmp_path):
    case = next(c for c in authored_suite("test")["cases"] if c["id"] == "STOCK-01")
    tmp_path = tmp_path / "workspace"
    materialize(case, tmp_path)
    (tmp_path / "report.md").write_text("Grounded reference " * 10 + case["fixture_receipt"])
    (tmp_path / "result.json").write_text(json.dumps(case["judge"]["expected"]))
    assert (await grade_authored(case, tmp_path, NoSandbox()))["hard_passed"]
    (tmp_path / "market.json").write_text('{"invented": true}')
    grade = await grade_authored(case, tmp_path, NoSandbox())
    assert not grade["hard_passed"] and not grade["checks"]["protected:market.json"]


async def test_backtest_fix_must_match_recomputed_causal_result(tmp_path):
    case = next(c for c in authored_suite("test")["cases"] if c["id"] == "QUANT-03")
    tmp_path = tmp_path / "workspace"
    materialize(case, tmp_path)
    expected = case["judge"]["expected"]
    (tmp_path / "result.json").write_text(json.dumps(expected))
    (tmp_path / "report.md").write_text(
        "flawed.py:1 lookahead; flawed.py:2 survivorship. " + case["fixture_receipt"]
    )
    (tmp_path / "analysis.py").write_text(
        "# Independent sandbox output supplied by this unit fixture\n"
    )
    (tmp_path / "corrected.json").write_text('{"claimed_fixed": true}')

    class Rerun:
        async def sandbox(self, *args, **kwargs):
            return json.dumps({"result": expected, "corrected": {"claimed_fixed": True}}).encode()

    grade = await grade_authored(case, tmp_path, Rerun())
    assert not grade["checks"]["reproducible_code"]
    assert not grade["checks"]["corrected_run_verified"] and not grade["passed"]
    (tmp_path / "corrected.json").write_text(json.dumps(case["judge"]["corrected_expected"]))
    # A correct-looking submitted file still fails when the independent rerun disagrees.
    assert not (await grade_authored(case, tmp_path, Rerun()))["hard_passed"]


async def test_correction_replay_requires_only_the_declared_generated_output(tmp_path):
    case = next(c for c in authored_suite("correction-output")["cases"] if c["id"] == "QUANT-03")
    workspace = tmp_path / "workspace"
    materialize(case, workspace)
    metadata = json.dumps(case["judge"]["expected"])
    corrected = json.dumps(case["judge"]["corrected_expected"])
    (workspace / "result.json").write_text(metadata)
    (workspace / "corrected.json").write_text(corrected)
    (workspace / "report.md").write_text(
        "flawed.py:1 lookahead and survivorship. " + case["fixture_receipt"]
    )
    script = (
        "from pathlib import Path\nPath('corrected.json').write_text(" + repr(corrected) + ")\n"
    )
    (workspace / "analysis.py").write_text(script)

    grade = await grade_authored(case, workspace, AnalysisReplay())
    assert grade["hard_passed"] and grade["checks"]["reproducible_code"]
    assert (workspace / "result.json").read_text() == metadata
    (workspace / "analysis.py").write_text(
        "from pathlib import Path\nPath('corrected.json').write_text('{}')\n"
    )
    rejected = await grade_authored(case, workspace, AnalysisReplay())
    assert not rejected["hard_passed"] and not rejected["checks"]["corrected_run_verified"]


@pytest.mark.parametrize("case_id", ["QUANT-01", "QUANT-02"])
async def test_strategy_replay_still_requires_regenerating_result(tmp_path, case_id):
    case = next(c for c in authored_suite("primary-output")["cases"] if c["id"] == case_id)
    workspace = tmp_path / "workspace"
    materialize(case, workspace)
    for name in case["judge"]["required"]:
        (workspace / name).write_text("placeholder")
    (workspace / "result.json").write_text(json.dumps(case["judge"]["expected"]))
    (workspace / "report.md").write_text("Grounded strategy report. " + case["fixture_receipt"])
    (workspace / "analysis.py").write_text("pass\n")
    grade = await grade_authored(case, workspace, AnalysisReplay())
    assert grade["checks"]["structured_result"]
    assert not grade["checks"]["reproducible_code"] and not grade["passed"]


@pytest.mark.parametrize("code", ["RSI_DOCKER_COMMAND_FAILED", "PRIVATE_PROVIDER_SECRET_123456"])
async def test_verification_failure_keeps_only_allowlisted_error_codes(tmp_path, code):
    case = next(c for c in authored_suite("verification-errors")["cases"] if c["id"] == "QUANT-03")
    workspace = tmp_path / "workspace"
    materialize(case, workspace)
    for name in ["result.json", "corrected.json"]:
        (workspace / name).write_text(json.dumps(case["judge"]["expected"]))
    (workspace / "analysis.py").write_text("pass\n")
    (workspace / "report.md").write_text("Grounded correction report. " + case["fixture_receipt"])

    class Failed:
        async def sandbox(self, *args, **kwargs):
            error = DomainError(code)
            error.args = ("PRIVATE_VERIFICATION_DETAIL",)
            raise error

    grade = await grade_authored(case, workspace, Failed())
    assert not grade["passed"] and not grade["checks"]["verification_completed"]
    failure = grade["evidence"][-1]
    assert failure["verification_error"] == "DomainError"
    assert failure.get("verification_error_code") == (
        code if code == "RSI_DOCKER_COMMAND_FAILED" else None
    )
    assert "PRIVATE_" not in json.dumps(grade)


def test_public_preconditions_are_presented_without_exposing_oracle():
    suite = authored_suite("independent-fairness-check")
    case = next(c for c in suite["cases"] if c["id"] == "CODE-01")
    assert "默认每页 5 条" in case["prompt"] and "页码从 1 开始" in case["prompt"]
    assert case["origin"]["recipe_revision"] == "authored-v10-separated-instructions"
    assert "expected" not in case["prompt"]


def test_corpus_contract_revision_preserves_previously_frozen_material(tmp_path):
    from roami_agent.improvement.evaluation.corpus import prepare_corpus
    from roami_agent.improvement.service import ImprovementStatus

    service = ImprovementStatus(tmp_path)
    root = service.ledger.path.parent / "corpus"
    root.mkdir(mode=0o700, parents=True)
    previous = root / "authored-40-v8.json"
    previous.write_bytes(b"original frozen suite evidence")
    v13 = root / "authored-40-v13.json"
    v13.write_bytes(b"previous v13 frozen evidence")
    v14 = root / "authored-40-v14.json"
    v14.write_bytes(b"previous v14 frozen evidence")
    prepare_corpus(service, "owner")
    assert v14.read_bytes() == b"previous v14 frozen evidence"
    assert v13.read_bytes() == b"previous v13 frozen evidence"
    assert previous.read_bytes() == b"original frozen suite evidence"
    revised = json.loads((root / "authored-40-v15.json").read_text())
    assert len(revised["cases"]) == 40
    identities = {c["id"]: c["origin"]["recipe_revision"] for c in revised["cases"]}
    assert identities["DEMO-02"] == identities["STOCK-01"] == "authored-v10-separated-instructions"
    assert identities["STOCK-03"] == "authored-v9-stock-evidence-contract"
    assert all(
        c["origin"]["recipe_revision"]
        in {
            "authored-v10-separated-instructions",
            "authored-v11-verified-backtest-summaries",
            "authored-v13-visible-quant-inputs",
            "authored-v14-explicit-trade-sides",
            "authored-v15-input-field-serialization",
        }
        for c in revised["cases"]
        if "执行要求（不是结果字段）" in c["prompt"]
    )


def test_public_contract_exposes_types_and_cost_rules_without_oracle_values():
    cases = {c["id"]: c for c in authored_suite("visible-contract")["cases"]}
    assert "source_receipt" in cases["DOC-05"]["prompt"]
    assert "stories和acceptance为需求ID到文字的对象" in cases["DOC-05"]["prompt"]
    assert "open*(1+slippage)" in cases["QUANT-01"]["prompt"]
    assert "equity数值数组" in cases["QUANT-01"]["prompt"]
    assert '"selected": ["fast整数", "slow整数"]' in cases["QUANT-02"]["prompt"]
    assert "不借用前一区间价格" in cases["QUANT-02"]["prompt"]
    assert "下一bar开盘执行" in cases["QUANT-02"]["prompt"]
    assert '"contract":' not in cases["QUANT-02"]["prompt"]
    assert "执行要求（不是结果字段）" in cases["QUANT-02"]["prompt"]
    assert (
        str(cases["QUANT-01"]["judge"]["expected"]["equity"][-1]) not in cases["QUANT-01"]["prompt"]
    )


async def test_pagination_metadata_is_allowed_only_by_the_revised_contract(tmp_path):
    case = next(c for c in authored_suite("response-contract")["cases"] if c["id"] == "CODE-01")
    workspace = tmp_path / "work"
    materialize(case, workspace)
    (workspace / "test_items.py").write_text("independent fixture tests")
    items = sorted(case["judge"]["items"], key=lambda x: x["name"])

    class Probe:
        async def sandbox(self, *args, **kwargs):
            return json.dumps(
                {
                    "responses": [
                        [200, {"items": items[:5], "total": 12, "page": 1}],
                        [200, {"items": items[10:], "total": 12, "page": 3}],
                        [200, {"items": [], "total": 12, "page": 99}],
                        *[[400, {}] for _ in range(4)],
                        [200, {}],
                    ],
                    "tests_passed": True,
                    "test_count": 3,
                }
            ).encode()

    assert (await grade_authored(case, workspace, Probe()))["hard_passed"]
    case["judge"].pop("pagination_metadata")
    assert not (await grade_authored(case, workspace, Probe()))["hard_passed"]


@pytest.mark.parametrize(
    ("code", "causal"),
    [
        ('"""The removed bug was prices.shift(-1)."""\npass\n', True),
        ("# Old implementation used prices.shift(-1)\npass\n", True),
        ("example = 'prices.shift(-1)'\n", True),
        ("prices.shift(1)\n", True),
        ("prices.shift(-1)\n", False),
        ("prices.shift(periods=-1)\n", False),
        ("prices.shift(-2)\n", False),
        ("prices.shift(\n", False),
    ],
)
async def test_backtest_causality_checks_executable_calls_not_explanations(tmp_path, code, causal):
    case = next(c for c in authored_suite("causality-source")["cases"] if c["id"] == "QUANT-03")
    workspace = tmp_path / "workspace"
    materialize(case, workspace)
    (workspace / "analysis.py").write_text(code)
    (workspace / "result.json").write_text(json.dumps(case["judge"]["expected"]))
    (workspace / "corrected.json").write_text(json.dumps(case["judge"]["corrected_expected"]))
    (workspace / "report.md").write_text(
        "flawed.py:1 lookahead and survivorship " + case["fixture_receipt"]
    )

    class Replay:
        async def sandbox(self, workspace, program, **kwargs):
            return json.dumps({"corrected": case["judge"]["corrected_expected"]}).encode()

    grade = await grade_authored(case, workspace, Replay())
    assert grade["checks"]["corrected_run_verified"]
    assert grade["checks"]["no_original_future_signal"] is causal


@pytest.mark.parametrize("case_id", ["QUANT-01", "QUANT-03"])
def test_trade_direction_serialization_is_public_and_versioned(case_id):
    from roami_agent.improvement.evaluation.case_catalog import case_definitions

    definition = next(c for c in case_definitions() if c["id"] == case_id)
    assert definition["output_format"] == {
        "trade_side_values": ["buy", "sell"],
        "trade_side_case": "lowercase",
    }
    case = next(c for c in authored_suite("trade-sides")["cases"] if c["id"] == case_id)
    assert "side 必须是小写字符串 buy 或 sell" in case["prompt"]
    assert case["origin"]["recipe_revision"] == "authored-v14-explicit-trade-sides"


def test_quant_data_quality_serialization_is_public_and_versioned():
    from roami_agent.improvement.evaluation.case_catalog import case_definitions

    definition = next(c for c in case_definitions() if c["id"] == "QUANT-05")
    fields = ["receipt", "execution_prices", "signal_prices"]
    assert definition["output_format"]["copy_input_fields"] == fields
    case = next(c for c in authored_suite("input-fields")["cases"] if c["id"] == "QUANT-05")
    assert "原样复制prices.json中的字符串字段" in case["prompt"]
    assert "解释放入report.md" in case["prompt"]
    assert all(field in case["prompt"] for field in fields)
    assert case["origin"]["recipe_revision"] == "authored-v15-input-field-serialization"


@pytest.mark.parametrize("field", ["receipt", "execution_prices", "signal_prices"])
async def test_quant_data_quality_still_rejects_replaced_input_fields(tmp_path, field):
    case = next(c for c in authored_suite("strict-input-fields")["cases"] if c["id"] == "QUANT-05")
    workspace = tmp_path / "workspace"
    materialize(case, workspace)
    wrong = {**case["judge"]["expected"], field: "explanation instead of original field"}
    (workspace / "analysis.py").write_text("pass\n")
    (workspace / "result.json").write_text(json.dumps(wrong))
    (workspace / "report.md").write_text(
        "Input prices.json remains synthetic and unresolved; no complete backtest is claimed. "
        + case["fixture_receipt"]
    )

    class Replay:
        async def sandbox(self, *args, **kwargs):
            return json.dumps({"result": wrong}).encode()

    grade = await grade_authored(case, workspace, Replay())
    assert not grade["hard_passed"]
    assert not grade["checks"]["structured_result"]
    assert not grade["checks"]["reproducible_code"]
