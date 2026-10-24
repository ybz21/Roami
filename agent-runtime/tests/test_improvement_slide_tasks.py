import base64
import io
import zipfile

import pytest

from roami_agent.improvement.contracts import freeze_suite, load_json, load_suite
from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.ledger import Ledger
from roami_agent.improvement.protocol_suite import protocol_suite
from roami_agent.improvement.slide_tasks import content_digest, package_parts, reference_delta
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
