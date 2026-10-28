"""Pinned Terminal-Bench tasks with upstream assertions in a disposable grader."""

import base64
import hashlib
import json
import re

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.integrations.artifact_paths import relative_file

TASKS = {"cancel-async-tasks": "CODE", "db-wal-recovery": "OPS"}


def import_terminal(root, *, task_id, revision):
    require(task_id in TASKS and bool(re.fullmatch(r"[a-f0-9]{40}", revision)))
    instructions = (root / "instruction.md").read_text()
    verifier = (root / "tests/test_outputs.py").read_text()
    test_driver = (root / "tests/test.py").read_text() if task_id == "cancel-async-tasks" else None
    assets = {}
    if task_id == "db-wal-recovery":
        for source, target in (("main.db", "main.db"), ("main.db-wal.encrypted", "main.db-wal")):
            data = (root / "environment" / source).read_bytes()
            require(len(data) <= 4_000_000)
            assets[target] = base64.b64encode(data).decode()
    case = {
        "id": "terminal_bench:" + task_id,
        "category": TASKS[task_id],
        "layer": "public_agent",
        "split": "public_test",
        "cluster": "terminal_bench:" + task_id,
        "prompt": instructions.replace("/app/", "/workspace/")
        + "\nThis frozen adaptation uses Python 3.12 in an offline container. Do not install dependencies. Use the provided workspace; shell calls must pass cwd=/workspace. Upstream result assertions are preserved with /app mapped to the grader's temporary working directory.",
        "counts_as_delivery": True,
        "files": {},
        "asset_files": assets,
        "limits": {"seconds": 900, "tokens": 384000, "requests": 64},
        "judge": {"kind": "terminal", "upstream_verifier": verifier, "test_driver": test_driver},
        "origin": {
            "benchmark": "terminal_bench",
            "task_id": task_id,
            "revision": revision,
            "source_split": "released_tasks",
            "input_sha256": digest({"instruction": instructions, "assets": assets}),
            "verifier_sha256": digest({"verifier": verifier, "driver": test_driver}),
            "adapter_revision": "terminal-offline-v1",
            "adapted": True,
            "adaptation": "Original result assertions; path /app remapped, Python 3.12 offline image, no upstream installation bootstrap. Not official environment-comparable.",
        },
    }
    return freeze_suite(
        "terminal-bench-" + task_id + "-v1", [case], official_leaderboard_comparable=False
    )


async def grade_terminal(case, workspace, executor):
    spec = case["judge"]
    require(
        digest({"verifier": spec["upstream_verifier"], "driver": spec["test_driver"]})
        == case["origin"]["verifier_sha256"],
        "RSI_VERIFIER_CHANGED",
    )
    name = "run.py" if case["origin"]["task_id"] == "cancel-async-tasks" else "recovered.json"
    artifact = relative_file(workspace, name)
    require(artifact.is_file() and artifact.stat().st_size <= 4_000_000, "RSI_ARTIFACT_UNAVAILABLE")
    evidence = {"path": name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    program = """import pathlib,tempfile,subprocess,sys,json,shutil
payload=json.loads(sys.stdin.read())
with tempfile.TemporaryDirectory() as d:
 root=pathlib.Path(d)
 for source in pathlib.Path('/workspace').iterdir():
  if source.is_file() and not source.is_symlink():shutil.copy2(source,root/source.name)
 (root/'frozen_test_outputs.py').write_text(payload['upstream_verifier'].replace('/app/',str(root)+'/'))
 if payload['test_driver'] is not None:(root/'test.py').write_text(payload['test_driver'])
 result=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider','--rootdir',str(root),str(root/'frozen_test_outputs.py')],cwd=root,capture_output=True,timeout=90)
 print(json.dumps({'exit_code':result.returncode,'output':(result.stdout+result.stderr).decode(errors='replace')[-200000:]}))
"""
    raw = await executor.sandbox(workspace, program, input=json.dumps(spec).encode(), timeout=100)
    result = json.loads(raw)
    passed = result["exit_code"] == 0
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "native_metric": float(passed),
        "grade_scope": "adapted_upstream_result_assertions",
        "official_leaderboard_comparable": False,
        "verifier_output": result["output"],
        "verifier_output_hash": digest(result["output"]),
        "evidence": [evidence],
    }
