"""Case directories preserve executable contracts and frozen display metadata."""

import json
from pathlib import Path

import pytest

from roami_agent.improvement.evaluation import case_catalog
from roami_agent.improvement.evaluation.case_catalog import (
    case_definitions,
    case_identity,
    read_definition,
)
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.corpus import authored_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.protocol.errors import DomainError


def directory(root, *, name="新增接口", description="增加分页接口并测试边界。"):
    folder = root / "case-1-code-01"
    folder.mkdir()
    (folder / "CASE.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n任务详情。\n"
    )
    (folder / "case.json").write_text('{"id":"CODE-01","kind":"real_workload"}')
    return folder


def test_directory_accepts_multiple_files_without_executing_them(tmp_path):
    folder = directory(tmp_path)
    (folder / "input").mkdir()
    (folder / "input" / "sample.csv").write_text("id,name\n1,A\n")
    (folder / "acceptance.md").write_text("边界测试须通过。")
    value = read_definition(folder)
    assert value["name"] == "新增接口"
    assert value["description"] == "增加分页接口并测试边界。"
    assert "files" not in value


@pytest.mark.parametrize(
    ("header", "code"),
    [
        ("name: 接口", "METADATA_REQUIRED"),
        ("name: 接口\ndescription: ", "METADATA_REQUIRED"),
        ("name: 接口\ndescription: 测试\nname: 重复", "METADATA_INVALID"),
        ('name: "未闭合\ndescription: 测试', "METADATA_INVALID"),
    ],
)
def test_required_metadata_rejects_missing_or_ambiguous_fields(tmp_path, header, code):
    folder = directory(tmp_path)
    (folder / "CASE.md").write_text(f"---\n{header}\n---\n")
    with pytest.raises(DomainError, match=code):
        read_definition(folder)


def test_contract_cannot_duplicate_metadata_or_disagree_with_directory(tmp_path):
    folder = directory(tmp_path)
    (folder / "case.json").write_text('{"id":"CODE-01","name":"other"}')
    with pytest.raises(DomainError, match="METADATA_DUPLICATED"):
        read_definition(folder)
    (folder / "case.json").write_text('{"id":"CODE-02"}')
    with pytest.raises(DomainError, match="ID_MISMATCH"):
        read_definition(folder)
    (folder / "case.json").unlink()
    (folder / "case.json").symlink_to(folder / "CASE.md")
    with pytest.raises(DomainError, match="METADATA_REQUIRED"):
        read_definition(folder)


def test_catalog_is_complete_and_execution_matches_frozen_contracts():
    definitions = case_definitions()
    assert len(definitions) == 61
    assert len({value["id"] for value in definitions}) == 61
    assert all(value["name"] and value["description"] for value in definitions)
    historical = json.loads(
        (
            Path(__file__).parents[2] / "docs/design/20261022-roami-agent-rsi/evaluation/cases.json"
        ).read_text()
    )
    # The historical bank also contains unselected candidates; all 40 executable contracts survive.
    old = historical if isinstance(historical, list) else historical["cases"]
    old_by_id = {value["id"]: value for value in old}
    own = [
        value
        for value in definitions
        if value["kind"] != "public_source_reference"
        and value.get("selected_in_mixed_suite_v1", True)
    ]
    assert len(own) == 40
    for value in own:
        previous = old_by_id[value["id"]]
        for key in ("prompt", "hard_assertions", "preconditions", "required_deliverables"):
            assert value[key] == previous[key]
    suite = authored_suite("fixture-seed")
    assert len(suite["cases"]) == 40
    assert all(case["name"] and case["description"] for case in suite["cases"])


def test_freezing_again_preserves_original_names_and_descriptions(tmp_path, monkeypatch):
    service = ImprovementStatus(tmp_path)
    case = authored_suite("metadata-fixture")["cases"][0]
    case.pop("name")
    case.pop("description")
    suite = freeze_suite("metadata", [case])
    run = service.runs.create(
        "local", "metadata", "diagnostic", {"suite_hash": suite["content_hash"]}
    )
    service.run_lifecycle.freeze_cases("local", run, suite)
    before = service.runs.get("local", run)["snapshot"]["case_definitions"]
    monkeypatch.setattr(
        case_catalog,
        "case_definitions",
        lambda: ({"id": "CODE-01", "name": "新名称", "description": "新描述"},),
    )
    service.run_lifecycle.freeze_cases("local", run, suite)
    assert service.runs.get("local", run)["snapshot"]["case_definitions"] == before
    assert case_identity(case)["name"] == "新名称"


def test_private_case_descriptions_never_enter_display_records():
    case = {
        "id": "CODE-01",
        "split": "holdout",
        "name": "秘密",
        "description": "隐藏答案",
        "prompt": "隐藏输入",
    }
    assert case_identity(case)["name"] == "CODE-01"
    assert case_identity(case)["description"] == ""
    result = trial_summary(case, {"grade": {}, "metrics": {}})
    assert result["name"] == "CODE-01" and result["description"] == ""


async def test_http_catalog_requires_local_owner_and_exposes_readable_metadata(store):
    import httpx

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    class Model:
        model = "fixture"

    runtime = Runtime(store, Model(), development_rsi=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://runtime",
    ) as client:
        assert (await client.get("/v1/improvement/cases")).status_code == 422
        assert (
            await client.get("/v1/improvement/cases", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
        response = await client.get("/v1/improvement/cases", headers={"X-Roami-Owner": "local"})
        assert response.status_code == 200
        cases = response.json()["data"]
        assert len(cases) == 61
        assert cases[0]["name"] == "新增分页接口"
        assert cases[0]["description"]
        assert "prompt" not in cases[0] and "judge" not in cases[0]


def test_visible_quant_inputs_are_the_actual_runtime_inputs_and_keep_receipts_private():
    import hashlib
    import runpy

    from roami_agent.improvement.evaluation.case_catalog import case_resource

    public = json.loads(case_resource("QUANT-02", "inputs/prices.json").read_text())
    generated = runpy.run_path(str(case_resource("QUANT-02", "generate.py")))["inputs"]()
    assert public == generated and len(public["bars"]) == 180 and "receipt" not in public
    case = next(
        value for value in authored_suite("resource-boundary")["cases"] if value["id"] == "QUANT-02"
    )
    runtime = json.loads(case["files"]["prices.json"])
    assert {key: value for key, value in runtime.items() if key != "receipt"} == public
    assert runtime["receipt"] and "tools.json" in case["files"]
    assert "expected" not in case["files"] and "judge" not in case["files"]
    assert (
        case["origin"]["resources"]["inputs/prices.json"]
        == hashlib.sha256(case_resource("QUANT-02", "inputs/prices.json").read_bytes()).hexdigest()
    )


def test_every_case_explains_its_data_tools_and_acceptance_without_claiming_execution():
    from roami_agent.improvement.evaluation.case_catalog import case_resource

    for definition in case_definitions():
        manifest = json.loads(case_resource(definition["id"], "materials.json").read_text())
        assert manifest["case_id"] == definition["id"]
        assert (
            manifest["data"]["kind"]
            and manifest["tools"]["kind"]
            and manifest["acceptance"]["kind"]
        )
        assert "execution_status" not in definition


def test_declared_resources_cannot_escape_the_case_directory(tmp_path):
    folder = directory(tmp_path)
    value = json.loads((folder / "case.json").read_text())
    (folder / "case.json").write_text(
        json.dumps({**value, "resources": {"inputs": ["../outside.json"]}})
    )
    with pytest.raises(DomainError):
        read_definition(folder)


def test_quant_selection_uses_the_declared_input_ranges_candidates_and_costs(tmp_path, monkeypatch):
    from roami_agent.improvement.evaluation.authored_fixtures import backtest, recipe
    from roami_agent.improvement.evaluation.case_catalog import case_resource

    public = json.loads(case_resource("QUANT-02", "inputs/prices.json").read_text())
    public.update(
        validation=[60, 120], test=[120, 175], candidates=[[2, 6]], fee=0.003, slippage=0.002
    )
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(public))
    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.case_catalog.case_resource",
        lambda case_id, name: (
            path if name == "inputs/prices.json" else case_resource(case_id, name)
        ),
    )
    fixture = recipe("QUANT-02", "resource-variation")
    actual = json.loads(fixture["files"]["prices.json"])
    assert {key: value for key, value in actual.items() if key != "receipt"} == public
    expected = fixture["judge"]["expected"]
    assert expected["selected"] == [2, 6] and expected["tried"] == [[2, 6]]
    assert expected["selection_range"] == [60, 120] and expected["test_range"] == [120, 175]
    assert (
        expected["test_final_equity"]
        == backtest(public["bars"][120:175], 2, 6, fee=0.003, slip=0.002)["equity"][-1]
    )


def test_additional_delivery_regression_has_materials_without_changing_the_default_suite():
    from roami_agent.improvement.evaluation.case_catalog import case_resource, resource_hashes

    definition = next(value for value in case_definitions() if value["id"] == "MECH-VD03")
    assert definition["selected_in_mixed_suite_v1"] is False
    assert definition["name"] and definition["description"]
    assert "scripts/run.py" in resource_hashes(definition)
    manifest = json.loads(case_resource(definition["id"], "materials.json").read_text())
    assert manifest["data"]["local_inputs"] is True
    assert manifest["acceptance"]["entry"] == "scripts/run.py"
    suite = authored_suite("extension-case-regression")
    assert len(suite["cases"]) == 40 and all(case["id"] != "MECH-VD03" for case in suite["cases"])
