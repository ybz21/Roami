"""OSWorld slide-state tasks with original comparisons and compact host-only references."""

import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, number, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.verification_windows import SLIDE_COMPARISON_SECONDS
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError

TASKS = {
    "04578141-1d42-4146-b9cf-6fab4ce5fd74": "45_2",
    "05dd4c1d-c489-4c85-8389-a7836c4f0567": "38_1",
}


def package_parts(data):
    require(len(data) <= 64_000_000, "RSI_INPUT_TOO_LARGE")
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        members = [i for i in bundle.infolist() if not i.is_dir()]
        require(
            len(members) <= 4000 and sum(i.file_size for i in members) <= 128_000_000,
            "RSI_INPUT_TOO_LARGE",
        )
        result = {}
        for info in members:
            name = PurePosixPath(info.filename)
            require(
                not name.is_absolute() and ".." not in name.parts and info.file_size <= 32_000_000,
                "RSI_ARCHIVE_PATH",
            )
            require(info.filename not in result, "RSI_DUPLICATE_SOURCE_ID")
            result[info.filename] = bundle.read(info)
        require("ppt/presentation.xml" in result, "RSI_PRESENTATION_REQUIRED")
        return result


def content_digest(parts):
    return digest(
        {name: hashlib.sha256(value).hexdigest() for name, value in sorted(parts.items())}
    )


def reference_delta(source, expected):
    delta = {
        "remove": sorted(set(source) - set(expected)),
        "replace": {
            name: base64.b64encode(data).decode()
            for name, data in expected.items()
            if source.get(name) != data
        },
        "content_sha256": content_digest(expected),
    }
    require(
        sum(len(value) for value in delta["replace"].values()) <= 4_000_000, "RSI_INPUT_TOO_LARGE"
    )
    return delta


def import_slides(metadata, materials, *, revision, data_revision):
    require(all(re.fullmatch(r"[a-f0-9]{40}", v) for v in (revision, data_revision)))
    task = json.loads(metadata.read_text())
    task_id = task["id"]
    require(task_id in TASKS)
    stem = TASKS[task_id]
    data = (materials / (stem + ".pptx")).read_bytes()
    source = package_parts(data)
    verifier = (materials / "slides.py").read_text()
    assets = {
        f"input-{i // 8_000_000:03}.part": base64.b64encode(data[i : i + 8_000_000]).decode()
        for i in range(0, len(data), 8_000_000)
    }
    references = [
        reference_delta(source, package_parts((materials / (stem + suffix + ".pptx")).read_bytes()))
        for suffix in ["_Gold", "_Gold_all_fonts"]
    ]
    options = task["evaluator"].get("options", [{}, {}])
    require(len(options) == 2)
    case = {
        "id": "osworld:" + task_id,
        "category": "DOC",
        "layer": "public_component",
        "split": "public_test",
        "cluster": "osworld:impress:" + task_id,
        "counts_as_delivery": True,
        "prompt": task["instruction"]
        + "\n\nThis is an extracted slide-state task, not a desktop GUI benchmark. The original presentation is /workspace/input.pptx. Make the requested edits and save an editable /workspace/updated.pptx, preserving input.pptx. Use native Worker and offline installed tools (python-pptx/LibreOffice); shell calls use cwd=/workspace. The original OSWorld PPTX comparison runs independently after exit; no reference presentations or verifier are provided to the Agent. Mouse/keyboard navigation, screenshots, and visual excellence are not measured by this adaptation.",
        "files": {},
        "asset_files": assets,
        "limits": {"seconds": 900, "tokens": 384000, "requests": 48},
        "judge": {
            "kind": "slides",
            "task_id": task_id,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_parts": sorted(assets),
            "verifier": verifier,
            "references": references,
            "options": options,
        },
        "origin": {
            "benchmark": "osworld",
            "task_id": task_id,
            "revision": revision,
            "data_revision": data_revision,
            "source_split": "libreoffice_impress",
            "input_sha256": digest(
                {
                    "instruction": task["instruction"],
                    "input_sha256": hashlib.sha256(data).hexdigest(),
                }
            ),
            "verifier_sha256": digest(verifier),
            "adapter_revision": "slide-state-original-comparison-v1",
            "adapted": True,
            "adaptation": "Original source file, instructions, two alternative references and original compare_pptx_files options. Extracted document-state contract, no VM/GUI interaction or visual quality score; not official leaderboard-comparable.",
        },
    }
    return freeze_suite(
        "osworld-" + task_id + "-slide-state-v1", [case], official_leaderboard_comparable=False
    )


def prepare_slides(case, workspace):
    spec = case["judge"]
    data = b"".join(
        base64.b64decode(case["asset_files"][p], validate=True) for p in spec["source_parts"]
    )
    require(hashlib.sha256(data).hexdigest() == spec["source_sha256"], "RSI_SOURCE_CHANGED")
    package_parts(data)
    (workspace / "input.pptx").write_bytes(data)
    (workspace / "input.pptx").chmod(0o600)
    for name in spec["source_parts"]:
        relative_file(workspace, name).unlink()


PROGRAM = r"""import base64,contextlib,hashlib,io,json,math,pathlib,tempfile,zipfile
payload=json.loads(__import__('sys').stdin.read())
namespace={'__name__':'frozen_slide_metric'}
with contextlib.redirect_stdout(io.StringIO()):exec(compile(payload['verifier'],'frozen_slides.py','exec'),namespace)
with zipfile.ZipFile('/workspace/input.pptx') as source:parts={n:source.read(n) for n in source.namelist() if not n.endswith('/')}
results=[];errors=[]
with tempfile.TemporaryDirectory() as directory:
 for i,reference in enumerate(payload['references']):
  expected=dict(parts)
  for name in reference['remove']:expected.pop(name)
  expected.update({n:base64.b64decode(v) for n,v in reference['replace'].items()})
  digest=hashlib.sha256(json.dumps({n:hashlib.sha256(v).hexdigest() for n,v in sorted(expected.items())},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
  assert digest==reference['content_sha256']
  target=pathlib.Path(directory)/(str(i)+'.pptx')
  with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as bundle:
   for name,data in expected.items():bundle.writestr(name,data)
  try:
   with contextlib.redirect_stdout(io.StringIO()):value=namespace['compare_pptx_files']('/workspace/updated.pptx',str(target),**dict(payload['options'][i],enable_debug=False))
   if type(value) in (int,float) and math.isfinite(value) and 0<=value<=1:results.append(value)
   else:results.append(None);errors.append('InvalidResult')
  except Exception as error:results.append(None);errors.append(type(error).__name__)
print(json.dumps({'results':results,'errors':errors},allow_nan=False))
"""


def comparison_receipt(payload, count):
    rows = payload.get("results") if isinstance(payload, dict) else None
    errors = payload.get("errors", []) if isinstance(payload, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != count
        or not isinstance(errors, list)
        or len(errors) > count
        or any(
            not isinstance(error, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error)
            for error in errors
        )
    ):
        return {"results": [None] * count, "errors": ["InvalidReceipt"]}
    values = [value if number(value, 0, 1) else None for value in rows]
    errors = list(errors)
    if any(value is not None and not number(value, 0, 1) for value in rows):
        errors.append("InvalidResult")
    # Older receipts replaced an unknown alternative with zero without recording its index.
    if errors and None not in values:
        values = [value if value == 1 else None for value in values]
    return {"results": values, "errors": errors}


async def grade_slides(case, workspace, executor):
    spec = case["judge"]
    require(digest(spec["verifier"]) == case["origin"]["verifier_sha256"], "RSI_VERIFIER_CHANGED")
    evidence = []
    checks = {}
    for name in ["input.pptx", "updated.pptx"]:
        path = relative_file(workspace, name)
        checks["artifact:" + name] = path.is_file() and path.stat().st_size <= 64_000_000
        if checks["artifact:" + name]:
            data = path.read_bytes()
            checksum = hashlib.sha256(data).hexdigest()
            evidence.append({"path": name, "sha256": checksum})
            try:
                package_parts(data)
            except (
                OSError,
                ValueError,
                zipfile.BadZipFile,
                RuntimeError,
                NotImplementedError,
                DomainError,
            ):
                checks["artifact:" + name] = False
            if name == "input.pptx":
                checks["source_unchanged"] = checksum == spec["source_sha256"]
    references = spec.get("references", [None, None])
    require(isinstance(references, list) and 1 <= len(references) <= 8)
    count = len(references)
    result = {"results": [None] * count, "errors": []}
    attempted = all(checks.values())
    if attempted:
        try:
            raw = await executor.sandbox(
                workspace,
                PROGRAM,
                input=json.dumps(spec).encode(),
                timeout=SLIDE_COMPARISON_SECONDS,
            )
            require(
                isinstance(raw, (bytes, str)) and len(raw) <= 200_000, "RSI_INVALID_NATIVE_RECEIPT"
            )
            payload = json.loads(raw)
            result = comparison_receipt(payload, count)
        except (DomainError, OSError, TimeoutError, ValueError) as error:
            result["errors"] = [type(error).__name__]
        checks["native_reference_match"] = any(v == 1 for v in result["results"])
        checks["native_comparison_completed"] = checks["native_reference_match"] or all(
            v is not None for v in result["results"]
        )
    complete = checks.get("native_comparison_completed", False)
    passed = all(checks.values()) and checks.get("native_reference_match", False)
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "reason": "assertions_passed"
        if passed
        else "native_verifier_failed"
        if attempted and (result["errors"] or not complete)
        else "native_reference_mismatch"
        if "native_reference_match" in checks
        else "assertion_failed",
        "checks": checks,
        **({"native_metric": float(passed)} if complete else {}),
        **({"native_reference_results": result["results"]} if attempted else {}),
        "native_verifier_ran": any(v is not None for v in result["results"]),
        "native_errors": result["errors"],
        "evidence": evidence,
        "grade_scope": "original_pptx_state_comparison_not_gui_or_visual_quality",
        "official_leaderboard_comparable": False,
    }
