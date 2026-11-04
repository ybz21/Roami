"""Default diagnostics follow the selected frozen suite, without changing explicit replays."""

import json

import pytest

from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.improvement.workflows.pipeline_runner import enqueue_diagnostic
from roami_agent.protocol.errors import DomainError

LIGHT_CASE_IDS = (
    "CODE-01",
    "QUANT-01",
    "DOC-05",
    "DEMO-01",
    "NEWS-01",
    "MECH-MR01",
    "MECH-CT01",
    "MECH-TL01",
    "MECH-MB01",
)


def configured_suite(tmp_path, finance=("finance-new",), missing=None):
    cases = [
        {
            "id": identifier,
            "category": "TEST",
            "cluster": identifier,
            "layer": "public_component" if identifier in finance else "authored_real",
            "split": "development",
            "prompt": "Only the public request.",
            "files": {},
            "limits": {"seconds": 10},
            "counts_as_delivery": True,
            "judge": {"kind": "numeric", "expected": 1},
            **(
                {
                    "origin": {
                        "benchmark": "finqa",
                        "task_id": identifier,
                        "revision": "a" * 40,
                        "source_split": "dev",
                        "adapter_revision": "fixture-v1",
                        "input_sha256": "b" * 64,
                    }
                }
                if identifier in finance
                else {"origin": None}
            ),
        }
        for identifier in (*LIGHT_CASE_IDS, *finance)
        if identifier != missing
    ]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(freeze_suite("selected", cases)))
    service = ImprovementStatus(tmp_path)
    service.control.register_machine(
        "local", {"id": "machine", "label": "M", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", path)
    service.control.save(
        "local", {"revision": 0, "suite_id": "selected", "machine_ids": ["machine"]}
    )
    return service, path


def queued_selection(service, run):
    with service.ledger.connection() as db:
        request = json.loads(
            db.execute("SELECT payload_json FROM rsi_requests WHERE id=?", (run["id"],)).fetchone()[
                0
            ]
        )
    assert (
        request["diagnostic"]["case_ids"]
        == service.runs.get("local", run["id"])["snapshot"]["case_ids"]
    )
    return request["diagnostic"]["case_ids"]


@pytest.mark.parametrize("finance", [("finance-new",), ("finqa:4f978c08853a6db6",), ("z", "a")])
def test_default_uses_one_current_finance_sample_with_nine_fixed_checks(tmp_path, finance):
    service, _ = configured_suite(tmp_path, finance)
    run = enqueue_diagnostic(service, "local", {"request_key": "default"})
    ids = queued_selection(service, run)
    assert ids == [*LIGHT_CASE_IDS[:5], min(finance), *LIGHT_CASE_IDS[5:]]
    assert len(ids) == len(set(ids)) == 10
    assert enqueue_diagnostic(service, "local", {"request_key": "default"}) == run


@pytest.mark.parametrize("finance,missing", [((), None), (("finance-new",), "CODE-01")])
def test_missing_default_coverage_creates_no_partial_run(tmp_path, finance, missing):
    service, _ = configured_suite(tmp_path, finance, missing)
    with pytest.raises(DomainError, match="RSI_CASE_NOT_FOUND"):
        enqueue_diagnostic(service, "local", {"request_key": "missing"})
    assert service.control.requests("local") == []
    with service.ledger.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM rsi_pipeline_runs").fetchone()[0] == 0


def test_explicit_selection_and_baseline_replay_do_not_inject_defaults(tmp_path):
    service, _ = configured_suite(tmp_path, finance=())
    run = enqueue_diagnostic(service, "local", {"request_key": "explicit", "case_ids": ["CODE-01"]})
    assert queued_selection(service, run) == ["CODE-01"]
    replay = enqueue_diagnostic(
        service, "local", {"request_key": "replay", "baseline_run": run["id"]}
    )
    assert queued_selection(service, replay) == ["CODE-01"]


@pytest.mark.parametrize("selection", [None, [], ["missing"], ["CODE-01", "CODE-01"]])
def test_invalid_explicit_selection_never_falls_back(tmp_path, selection):
    service, _ = configured_suite(tmp_path)
    with pytest.raises(DomainError):
        enqueue_diagnostic(service, "local", {"request_key": "invalid", "case_ids": selection})
    assert service.control.requests("local") == []


def test_registered_hash_is_checked_before_resolving_defaults(tmp_path):
    service, path = configured_suite(tmp_path)
    raw = json.loads(path.read_text())
    raw["cases"][0]["prompt"] = "Changed public input."
    path.write_text(json.dumps(freeze_suite("selected", raw["cases"])))
    with pytest.raises(DomainError, match="RSI_SUITE_HASH_MISMATCH"):
        enqueue_diagnostic(service, "local", {"request_key": "changed"})
    assert service.control.requests("local") == []
