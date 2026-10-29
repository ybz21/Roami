"""Pinned AgenticVBench media inputs and host-only original verifier execution."""

import base64
import hashlib
import io
import json
import math
import re
import wave
import zipfile
from pathlib import PurePosixPath

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.integrations.artifact_paths import relative_file

TASKS = {"assembly": "agentic-vbench-assembly-task1", "repair": "exp-codec-restore-task01"}


def import_media(root, archive, *, kind, revision, data_revision):
    require(kind in TASKS)
    require(all(re.fullmatch(r"[a-f0-9]{40}", v) for v in (revision, data_revision)))
    require(archive.stat().st_size <= 24_000_000, "RSI_INPUT_TOO_LARGE")
    assets, golden = {}, {}
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        require(len(members) <= 64 and sum(m.file_size for m in members) <= 32_000_000)
        for member in members:
            if member.is_dir():
                continue
            name = member.filename
            require(not name.startswith("/") and ".." not in PurePosixPath(name).parts)
            require(member.file_size <= 10_000_000, "RSI_INPUT_TOO_LARGE")
            if kind == "assembly":
                require(bool(re.fullmatch(r"(?:[1-9]|1[0-2])\.mp4", name)))
                destination, key = assets, "materials/" + name
            elif name == "input/noisy.wav":
                destination, key = assets, "materials/noisy.wav"
            else:
                require(
                    name in {"golden/clean.wav", "golden/window.json", "golden/sig_bak_ovr.onnx"}
                )
                destination, key = golden, name.removeprefix("golden/")
            require(key not in destination, "RSI_DUPLICATE_SOURCE_ID")
            destination[key] = base64.b64encode(bundle.read(member)).decode()
    require(
        set(assets) == {f"materials/{n}.mp4" for n in range(1, 13)}
        if kind == "assembly"
        else set(assets) == {"materials/noisy.wav"}
        and set(golden) == {"clean.wav", "window.json", "sig_bak_ovr.onnx"}
    )
    instruction = (root / "steps/solve/instruction.md").read_text()
    verifier = (root / "steps/solve/tests/judge.py").read_text()
    case = {
        "id": "agentic_vbench:" + TASKS[kind],
        "category": "VIDEO",
        "layer": "public_agent",
        "split": "public_test",
        "cluster": "agentic_vbench:" + TASKS[kind],
        "prompt": instruction
        + "\nRSI adaptation: offline prepared environment; no dependency installation. Delegate native execution in /workspace. Shell calls must use cwd=/workspace. Preserve all supplied inputs. The original host-only verifier is followed by fixed delivery checks; assembly requires reward=1, audio repair reward>=0.8. No reference files or verifier are exposed to the Agent. This is not an official leaderboard run.",
        "files": {"output/.keep": "", "work/.keep": ""},
        "asset_files": assets,
        "counts_as_delivery": True,
        "limits": {"seconds": 1800, "tokens": 512000, "requests": 64},
        "judge": {
            "kind": "media",
            "media_kind": kind,
            "upstream_verifier": verifier,
            "golden": golden,
            "minimum_reward": 1.0 if kind == "assembly" else 0.8,
        },
        "origin": {
            "benchmark": "agentic_vbench",
            "task_id": TASKS[kind],
            "revision": revision,
            "data_revision": data_revision,
            "source_split": "released_tasks",
            "input_sha256": digest({"instruction": instruction, "assets": assets}),
            "verifier_sha256": digest(verifier),
            "adapter_revision": "native-media-host-v1",
            "adapted": True,
            "adaptation": "Original verifier; offline dependency image; frozen source hashes, audio PCM/sample-count or video full-range/contiguity checks; fixed RSI reward thresholds. Not official environment-comparable.",
        },
    }
    return freeze_suite(
        "agentic-vbench-" + kind + "-sample-v1", [case], official_leaderboard_comparable=False
    )


PROGRAM = r"""import base64,hashlib,json,math,pathlib,re,subprocess,sys,tempfile
payload=json.loads(sys.stdin.read());work=pathlib.Path('/workspace')
def duration(path):
 p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,check=True,timeout=15)
 return float(json.loads(p.stdout)['format']['duration'])
with tempfile.TemporaryDirectory() as directory:
 root=pathlib.Path(directory);judge=root/'judge.py';judge.write_text(payload['upstream_verifier'])
 for name,encoded in payload['golden'].items():(root/name).write_bytes(base64.b64decode(encoded))
 reward=root/'reward.json';args=['--reward-json',str(reward),'--reward-txt',str(root/'reward.txt')]
 checks={}
 if payload['media_kind']=='repair':
  args+=['--enhanced',str(work/'output/enhanced.wav'),'--clean',str(root/'clean.wav'),'--window-json',str(root/'window.json'),'--dnsmos-model',str(root/'sig_bak_ovr.onnx')]
 else:
  manifest=json.loads((work/'output/solution.json').read_text());segments=manifest.get('segments',[])
  checks['four_segments']=len(segments)==4;checks['full_contiguous_ranges']=True;offset=0;used=[]
  try:
   for segment in segments:
    name=str(segment['source']).removesuffix('.mp4');assert re.fullmatch(r'(?:[1-9]|1[0-2])',name)
    source=duration(work/'materials'/(name+'.mp4'));start,end=segment['source_range'];a,b=segment['output']
    assert all(type(x) in (int,float) and math.isfinite(x) for x in (start,end,a,b))
    assert abs(start)<=0.001 and abs(end-source)<=0.1 and abs(a-offset)<=0.05 and b>a and abs((b-a)-source)<=0.1
    offset=b;used.append(name)
   assert len(set(used))==4 and abs(duration(work/'output/solution.mp4')-offset)<=0.1
  except (AssertionError,KeyError,TypeError,ValueError,subprocess.SubprocessError):checks['full_contiguous_ranges']=False
  args+=['--solution',str(work/'output/solution.json'),'--solution-mp4',str(work/'output/solution.mp4'),'--materials-dir',str(work/'materials')]
 result=None;data=None;score=None
 try:result=subprocess.run([sys.executable,str(judge),*args],cwd=root,capture_output=True,timeout=300)
 except subprocess.TimeoutExpired:pass
 checks['verifier_exited']=result is not None and result.returncode==0 and reward.is_file()
 try:
  if reward.is_file() and reward.stat().st_size<=200000:
   data=reward.read_bytes();receipt=json.loads(data)
   if isinstance(receipt,dict):score=receipt.get('reward')
 except (OSError,ValueError,UnicodeError):pass
 valid=checks['verifier_exited'] and type(score) in (int,float) and 0<=score<=1 and math.isfinite(score)
 checks['verifier_result_valid']=valid
 print(json.dumps({'checks':checks,'reward':score if valid else None,'native_result_sha256':hashlib.sha256(data).hexdigest() if data is not None else None,'diagnostic':result.stderr.decode(errors='replace')[-8000:] if result is not None and result.returncode else ''},allow_nan=False))
"""


async def grade_media(case, workspace, executor):
    spec = case["judge"]
    require(
        digest(spec["upstream_verifier"]) == case["origin"]["verifier_sha256"],
        "RSI_VERIFIER_CHANGED",
    )
    checks, evidence = {}, []
    for name, encoded in case["asset_files"].items():
        path = relative_file(workspace, name)
        expected = hashlib.sha256(base64.b64decode(encoded)).hexdigest()
        checks["source:" + name] = (
            path.is_file()
            and path.stat().st_size <= 10_000_000
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected
        )
    names = (
        ["output/enhanced.wav"]
        if spec["media_kind"] == "repair"
        else ["output/solution.mp4", "output/solution.json"]
    )
    for name in names:
        path = relative_file(workspace, name)
        checks["artifact:" + name] = path.is_file() and path.stat().st_size <= (
            200000 if name.endswith(".json") else 32_000_000
        )
        if checks["artifact:" + name]:
            evidence.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if spec["media_kind"] == "repair" and all(checks.values()):
        try:
            with (
                wave.open(
                    io.BytesIO(base64.b64decode(case["asset_files"]["materials/noisy.wav"]))
                ) as source,
                wave.open(str(relative_file(workspace, "output/enhanced.wav"))) as output,
            ):
                checks["pcm_shape"] = (
                    output.getnchannels() == 1
                    and output.getframerate() == 16000
                    and output.getsampwidth() == 2
                    and output.getnframes() == source.getnframes()
                )
        except (OSError, EOFError, wave.Error):
            checks["pcm_shape"] = False
    result = {"reward": None}
    if all(checks.values()):
        result = json.loads(
            await executor.sandbox(workspace, PROGRAM, input=json.dumps(spec).encode(), timeout=330)
        )
        checks.update(result["checks"])
    score = result["reward"]
    valid = (
        checks.get("verifier_exited") is True
        and type(score) in {int, float}
        and 0 <= score <= 1
        and math.isfinite(score)
        and checks.get("verifier_result_valid") is not False
    )
    checks["verifier_result_valid"] = valid
    verified = all(checks.values())
    checks["native_metric_threshold"] = valid and score >= spec["minimum_reward"]
    passed = all(checks.values())
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        **({"native_metric": score} if valid else {}),
        "native_metric_minimum": spec["minimum_reward"],
        "reason": "assertions_passed"
        if passed
        else "native_metric_below_threshold"
        if verified
        else "assertion_failed",
        "grade_scope": "original_media_verifier_plus_frozen_delivery_checks",
        "checks": checks,
        "evidence": evidence,
        "native_result_sha256": result.get("native_result_sha256"),
        "official_leaderboard_comparable": False,
    }
