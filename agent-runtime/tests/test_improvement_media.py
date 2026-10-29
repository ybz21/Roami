import base64
import io
import json
import wave
import zipfile

import pytest

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.media_tasks import grade_media, import_media
from roami_agent.improvement.evaluation.contracts import agent_view
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.protocol.errors import DomainError


def wav(frames):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, frames, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * frames)
    return output.getvalue()


def package(tmp_path, members):
    root = tmp_path / "task"
    (root / "steps/solve/tests").mkdir(parents=True)
    (root / "steps/solve/instruction.md").write_text("Restore the input audio.")
    (root / "steps/solve/tests/judge.py").write_text("private oracle text")
    archive = tmp_path / "media.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return root, archive


def test_import_keeps_oracles_outside_agent_and_rejects_archive_traversal(tmp_path):
    members = {
        "input/noisy.wav": wav(64),
        "golden/clean.wav": wav(64),
        "golden/window.json": b"{}",
        "golden/sig_bak_ovr.onnx": b"private model",
    }
    root, archive = package(tmp_path, members)
    case = import_media(root, archive, kind="repair", revision="a" * 40, data_revision="b" * 40)[
        "cases"
    ][0]
    view = agent_view(case, tmp_path / "workspace")
    assert "judge" not in view and "golden" not in str(view) and "private oracle" not in str(view)
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("../escape", b"bad")
    with pytest.raises(DomainError):
        import_media(root, archive, kind="repair", revision="a" * 40, data_revision="b" * 40)


async def test_wrong_audio_shape_and_modified_input_do_not_reach_native_judge(tmp_path):
    source = wav(64)
    case = {
        "files": {},
        "asset_files": {"materials/noisy.wav": base64.b64encode(source).decode()},
        "judge": {"media_kind": "repair", "upstream_verifier": "private", "minimum_reward": 0.8},
        "origin": {"verifier_sha256": digest("private")},
    }
    materialize(case, tmp_path / "work")
    output = tmp_path / "work/output/enhanced.wav"
    output.parent.mkdir()
    output.write_bytes(wav(63))

    class Forbidden:
        async def sandbox(self, *args, **kwargs):
            raise AssertionError("Invalid shape must fail locally")

    grade = await grade_media(case, tmp_path / "work", Forbidden())
    assert not grade["passed"] and not grade["checks"]["pcm_shape"]
    output.write_bytes(source)
    (tmp_path / "work/materials/noisy.wav").write_bytes(wav(63))
    grade = await grade_media(case, tmp_path / "work", Forbidden())
    assert not grade["passed"] and not grade["checks"]["source:materials/noisy.wav"]


@pytest.mark.parametrize(
    "score,exited,expected,reason",
    [
        (0.7, True, False, "native_metric_below_threshold"),
        (0.8, True, True, "assertions_passed"),
        (1.0, True, True, "assertions_passed"),
        (0.9, False, False, "assertion_failed"),
    ],
)
async def test_native_reward_and_delivery_contract_must_both_pass(
    tmp_path, score, exited, expected, reason
):
    source = wav(64)
    case = {
        "files": {},
        "asset_files": {"materials/noisy.wav": base64.b64encode(source).decode()},
        "judge": {
            "media_kind": "repair",
            "upstream_verifier": "private",
            "minimum_reward": 0.8,
            "golden": {},
        },
        "origin": {"verifier_sha256": digest("private")},
    }
    materialize(case, tmp_path / "work")
    output = tmp_path / "work/output/enhanced.wav"
    output.parent.mkdir()
    output.write_bytes(source)

    class Scored:
        async def sandbox(self, *args, **kwargs):
            return json.dumps({"reward": score, "checks": {"verifier_exited": exited}}).encode()

    grade = await grade_media(case, tmp_path / "work", Scored())
    assert grade["passed"] is expected
    if exited:
        assert grade["native_metric"] == score
    else:
        assert "native_metric" not in grade
    assert grade["native_metric_minimum"] == 0.8
    assert grade["checks"]["native_metric_threshold"] is (exited and score >= 0.8)
    assert grade["reason"] == reason
