import hashlib
import io
import json
import wave
from pathlib import Path

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_transcription import MediaTranscription, transcript_receipt

_wav = io.BytesIO()
with wave.open(_wav, "wb") as _audio:
    _audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
    _audio.writeframes(b"\x00\x00" * 16000)
AUDIO = _wav.getvalue()


def receipt():
    data = {"text": "Exact final audio transcript"}
    body = json.dumps({"data": data})
    return {
        "input": {"sha256": hashlib.sha256(AUDIO).hexdigest(), "bytes": len(AUDIO)},
        "response": {
            "body": body,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "status": 200,
        },
        "data": data,
    }


@pytest.mark.parametrize("fault", ["audio", "body", "text", "truncated", "status", "shape"])
def test_unbound_or_incomplete_transcription_cannot_support_review(fault):
    value = receipt()
    if fault == "audio":
        value["input"]["sha256"] = "0" * 64
    elif fault == "body":
        value["response"]["body"] += " "
    elif fault == "text":
        value["data"] = {"text": "Unverified replacement"}
    elif fault == "truncated":
        value["response"]["truncated"] = True
    elif fault == "status":
        value["response"]["status"] = 503
    else:
        value["response"]["body"] = 42
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED"):
        transcript_receipt(json.dumps(value), AUDIO)


async def test_saved_node_speech_command_runs_once_and_cleans_private_audio(tmp_path):
    executable = tmp_path / "roami"
    arguments = tmp_path / "arguments.json"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys\n"
        f"open({str(arguments)!r},'w').write(json.dumps(sys.argv[1:]))\n"
        f"print({json.dumps(receipt())!r})\n"
    )
    executable.chmod(0o700)
    actual = await MediaTranscription(executable).transcribe(AUDIO)
    assert actual == receipt()
    args = json.loads(arguments.read_text())
    assert args[:2] == ["speech", "transcribe"]
    assert "--server" not in args and "--model" not in args
    assert args[args.index("--expected-file-sha256") + 1] == hashlib.sha256(AUDIO).hexdigest()
    assert not Path(args[args.index("--file") + 1]).exists()


async def test_failed_speech_request_is_not_retried(tmp_path):
    executable, calls = tmp_path / "roami", tmp_path / "calls"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        f"open({str(calls)!r},'a').write('called\\n')\nraise SystemExit(1)\n"
    )
    executable.chmod(0o700)
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_UNAVAILABLE"):
        await MediaTranscription(executable).transcribe(AUDIO)
    assert calls.read_text() == "called\n"
