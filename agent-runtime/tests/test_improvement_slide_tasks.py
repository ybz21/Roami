import base64
import hashlib
import io
import json
import zipfile

import pytest

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.slide_tasks import (
    content_digest,
    grade_slides,
    package_parts,
    reference_delta,
)
from roami_agent.improvement.evaluation.contracts import freeze_suite, load_suite
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.integrations.json_documents import load_json
from roami_agent.improvement.persistence.control import ImprovementControl
from roami_agent.improvement.persistence.ledger import Ledger
from roami_agent.protocol.errors import DomainError


def package(parts):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as bundle:
        for name, value in parts.items():
            bundle.writestr(name, value)
    return result.getvalue()


def test_reference_delta_preserves_large_media_without_copying_it_into_oracle():
    source = {"ppt/presentation.xml": b"original", "ppt/media/photo.png": b"unchanged media"}
    expected = {**source, "ppt/presentation.xml": b"edited"}
    delta = reference_delta(source, expected)
    assert set(delta["replace"]) == {"ppt/presentation.xml"}
    rebuilt = dict(source)
    rebuilt.update({name: base64.b64decode(data) for name, data in delta["replace"].items()})
    assert content_digest(rebuilt) == delta["content_sha256"] == content_digest(expected)


@pytest.mark.parametrize("name", ["../escape", "/absolute"])
def test_presentation_package_rejects_unsafe_entries(name):
    with pytest.raises(DomainError, match="ARCHIVE_PATH"):
        package_parts(package({"ppt/presentation.xml": b"content", name: b"bad"}))


def test_registration_and_suite_reader_accept_large_frozen_inputs(tmp_path):
    case = protocol_suite()["cases"][0]
    case["asset_files"] = {f"part-{i}": "AAAA" * 262144 for i in range(17)}
    suite = freeze_suite("large-source-contract", [case])
    path = tmp_path / "suite.json"
    private_json(path, suite)
    with pytest.raises(DomainError, match="INPUT_TOO_LARGE"):
        load_json(path)
    control = ImprovementControl(Ledger(tmp_path / "ledger.sqlite3"))
    registered = control.register_suite("owner", path)
    loaded = load_suite(path)
    assert loaded["content_hash"] == registered["content_hash"] == suite["content_hash"]
    assert len(loaded["cases"]) == 1


@pytest.mark.parametrize(
    ("results", "errors", "passed", "reason"),
    [
        ([0, 0], [], False, "native_reference_mismatch"),
        ([None, 0], ["ValueError"], False, "native_verifier_failed"),
        ([0, 1], [], True, "assertions_passed"),
        ([1, None], ["ValueError"], True, "assertions_passed"),
    ],
)
async def test_slide_summary_explains_comparison_without_changing_alternative_acceptance(
    tmp_path, results, errors, passed, reason
):
    source = package({"ppt/presentation.xml": b"original"})
    (tmp_path / "input.pptx").write_bytes(source)
    (tmp_path / "updated.pptx").write_bytes(source)
    case = {
        "id": "slide-evidence",
        "judge": {"verifier": "frozen", "source_sha256": hashlib.sha256(source).hexdigest()},
        "origin": {"verifier_sha256": digest("frozen")},
    }

    class Executor:
        async def sandbox(self, workspace, program, **kwargs):
            return json.dumps({"results": results, "errors": errors}).encode()

    grade = await grade_slides(case, tmp_path, Executor())
    summary = trial_summary(case, {"grade": grade})
    assert grade["native_reference_results"] == results and grade["native_errors"] == errors
    assert grade["passed"] is passed and summary["passed"] is passed
    assert grade["reason"] == reason
    assert summary["checks"]["native_reference_match"] is passed
    assert ("check:native_reference_match" in summary["signals"]) is not passed
    assert (reason in summary["signals"]) is not passed
    assert "UNKNOWN" not in summary["signals"]


async def test_slide_missing_artifact_does_not_claim_comparison_ran(tmp_path):
    source = package({"ppt/presentation.xml": b"original"})
    (tmp_path / "input.pptx").write_bytes(source)
    case = {
        "id": "slide-evidence",
        "judge": {"verifier": "frozen", "source_sha256": hashlib.sha256(source).hexdigest()},
        "origin": {"verifier_sha256": digest("frozen")},
    }

    class Executor:
        async def sandbox(self, *args, **kwargs):
            pytest.fail("Missing delivery must not invoke the comparator")

    grade = await grade_slides(case, tmp_path, Executor())
    assert not grade["passed"] and grade["reason"] == "assertion_failed"
    assert not grade["checks"]["artifact:updated.pptx"]
    assert "native_reference_match" not in grade["checks"]
