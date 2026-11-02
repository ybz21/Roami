"""Independent execution of private Python contracts; answers stay on the host."""

import hashlib
import json

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.authored_grading import close_json
from roami_agent.improvement.integrations.artifact_paths import relative_file


async def grade_code_contract(case, workspace, executor):
    spec = case["judge"]
    path = relative_file(workspace, spec["module"])
    require(path.is_file() and path.stat().st_size <= 200000, "RSI_ARTIFACT_UNAVAILABLE")
    evidence = {"path": spec["module"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    program = """import contextlib,importlib.util,io,json,sys
payload=json.loads(sys.stdin.read())
with contextlib.redirect_stdout(io.StringIO()):
 spec=importlib.util.spec_from_file_location('student','/workspace/'+payload['module'])
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 results=[module.solve(value) for value in payload['inputs']]
print(json.dumps({'results':results},allow_nan=False))
"""
    # Only inputs cross the sandbox boundary. Expected values stay in this process.
    payload = {"module": spec["module"], "inputs": spec["probes"]}
    raw = await executor.sandbox(workspace, program, input=json.dumps(payload).encode(), timeout=60)
    actual = json.loads(raw)
    passed = close_json(actual.get("results"), spec["expected"], tolerance=1e-8)
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "grade_scope": "bounded_private_code_contract",
        "evidence": [evidence],
        "result_hash": digest(actual),
        "probe_count": len(spec["probes"]),
    }
