"""Frozen MLAgentBench vectorization adaptation with independent wall-clock timing."""

import ast
import json
import math
import re
import statistics
import time

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.authored_grading import close_json
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError


def skeleton(source):
    tree = ast.parse(source)
    found = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Conv2DLayer":
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name == "forward":
                    method.body = [ast.Pass()]
                    found += 1
    require(found == 1, "RSI_FORWARD_CONTRACT_REQUIRED")
    return ast.dump(tree, include_attributes=False)


def import_vectorization(root, *, revision):
    require(bool(re.fullmatch(r"[a-f0-9]{40}", revision)))
    upstream = (root / "env/train.py").read_text()
    assignment = "output[index,h,w,filter_index] = result"
    require(upstream.count(assignment) == 1, "RSI_NUMPY_COMPATIBILITY_CONTRACT")
    source = upstream.replace(assignment, "output[index,h,w,filter_index] = float(result.item())")
    prompt = (root / "scripts/research_problem.txt").read_text()
    skeleton(source)
    case = {
        "id": "mlagentbench:vectorization",
        "category": "LAB",
        "layer": "public_agent",
        "split": "public_test",
        "cluster": "mlagentbench:vectorization",
        "prompt": prompt
        + "\nThe supplied baseline explicitly converts a size-one array to a scalar for modern NumPy compatibility. Edit only Conv2DLayer.forward in train.py. Preserve all other syntax. Use installed NumPy; no network. Run the script to produce submission.csv. Independently checked outputs must match the frozen baseline on several shapes and activations. The host compares median sandbox wall time over four alternating pairs, including imports and serialization: candidate must take <=90% of baseline. This adaptation is not the official runtime score. Shell calls must pass cwd=/workspace.",
        "counts_as_delivery": True,
        "files": {"train.py": source},
        "limits": {"seconds": 900, "tokens": 384000, "requests": 64},
        "judge": {"kind": "vectorization", "source": source, "max_time_ratio": 0.9},
        "origin": {
            "benchmark": "mlagentbench",
            "task_id": "vectorization",
            "revision": revision,
            "source_split": "released_tasks",
            "input_sha256": digest({"source": source, "prompt": prompt}),
            "upstream_source_digest": digest(upstream),
            "compatibility_patch": "explicit_size_one_scalar_conversion",
            "adapter_revision": "numpy-vectorization-host-v1",
            "adapted": True,
            "adaptation": "Explicit scalar conversion for modern NumPy; frozen forward-only edit, numerical checks and four alternating host sandbox time pairs (median ratio <=0.9); not official environment or submitted-time comparable.",
        },
    }
    return freeze_suite(
        "mlagentbench-vectorization-sample-v1", [case], official_leaderboard_comparable=False
    )


PROBE = """import json,sys,numpy as np
payload=json.loads(sys.stdin.read());namespace={'__name__':'isolated_benchmark'}
exec(compile(payload['source'],'train.py','exec'),namespace)
results=[]
for shape,filters,kernel,stride,padding,activation in [([2,6,7,2],3,3,1,1,'relu'),([1,5,5,1],2,2,2,0,None),([32,64,64,3],8,3,2,2,'relu')]:
 np.random.seed(1847);features=np.random.randn(*shape)
 layer=namespace['Conv2DLayer'](shape[-1],filters,kernel,stride,padding,activation)
 results.append(layer.forward(features).tolist())
print(json.dumps({'outputs':results},allow_nan=False))
"""


async def grade_vectorization(case, workspace, executor):
    spec = case["judge"]
    path = relative_file(workspace, "train.py")
    require(path.is_file() and path.stat().st_size <= 200000, "RSI_ARTIFACT_UNAVAILABLE")
    source = path.read_text()
    try:
        checks = {
            "forward_only": skeleton(source) == skeleton(spec["source"]),
            "actual_change": ast.dump(ast.parse(source)) != ast.dump(ast.parse(spec["source"])),
        }
    except (SyntaxError, DomainError):
        checks = {"forward_only": False, "actual_change": False}
    csv_path = relative_file(workspace, "submission.csv")
    try:
        require(csv_path.stat().st_size <= 100000)
        reported = float(csv_path.read_text().strip().splitlines()[0].split(";")[0])
        checks["submission_record"] = math.isfinite(reported) and reported > 0
    except (OSError, ValueError):
        checks["submission_record"] = False
    measurements = {"baseline": [], "candidate": []}
    outputs = {}
    if all(checks.values()):
        checks["numerical_equivalence"] = True
        for repetition in range(4):
            arms = ("baseline", "candidate") if repetition % 2 == 0 else ("candidate", "baseline")
            for arm in arms:
                code = spec["source"] if arm == "baseline" else source
                started = time.monotonic()
                raw = await executor.sandbox(
                    workspace, PROBE, input=json.dumps({"source": code}).encode(), timeout=90
                )
                measurements[arm].append((time.monotonic() - started) * 1000)
                outputs[arm] = json.loads(raw)["outputs"]
                if len(outputs) == 2:
                    checks["numerical_equivalence"] &= close_json(
                        outputs["candidate"], outputs["baseline"], 1e-8
                    )
        checks["measured_speed"] = (
            statistics.median(measurements["candidate"])
            <= statistics.median(measurements["baseline"]) * spec["max_time_ratio"]
        )
    passed = all(checks.values())
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "checks": checks,
        "grade_scope": "adapted_numpy_forward_correctness_and_host_time",
        "timing_scope": "sandbox_wall_including_startup_imports_serialization",
        "benchmark_ms": measurements,
        "artifact_hash": digest(source),
        "official_leaderboard_comparable": False,
    }
