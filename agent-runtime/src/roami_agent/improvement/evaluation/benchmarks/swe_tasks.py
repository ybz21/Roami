"""SWE-bench source snapshots, native test images, and independent patch grading."""

import base64
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import tarfile
from pathlib import PurePosixPath

from roami_agent.improvement.domain.contracts import DIMENSIONS, digest, require
from roami_agent.improvement.domain.scoring import quality
from roami_agent.improvement.evaluation.contracts import freeze_suite
from roami_agent.improvement.evaluation.execution.project_snapshot import (
    MAX_PROJECT_BYTES,
    unpack_project,
)
from roami_agent.improvement.integrations.artifact_paths import relative_file

TASKS = {
    "pylint-dev__pylint-6903": ("pylint/", "tests/test_pylint_runners.py"),
    "scikit-learn__scikit-learn-13496": ("sklearn/", "sklearn/ensemble/tests/test_iforest.py"),
}
IMAGE_PATTERN = r"swebench/sweb\.eval\.x86_64\.[a-z0-9_-]+@sha256:[a-f0-9]{64}"

CLIENT = """import json,socket,sys
request=json.dumps({'argv':sys.argv[1:]}).encode()+b'\\n'
assert len(request)<=64000
with socket.socket(socket.AF_UNIX) as connection:
 connection.connect('/model/project.sock');connection.sendall(request);connection.shutdown(socket.SHUT_WR)
 chunks=[];size=0
 while chunk:=connection.recv(65536):
  size+=len(chunk);assert size<=2100000;chunks.append(chunk)
response=json.loads(b''.join(chunks));print(response.get('output',response.get('error','')),end='')
sys.exit(response.get('exit_code',1))
"""


async def resolve_image(reference):
    from roami_agent.improvement.evaluation.execution.containers import docker_command

    require(bool(re.fullmatch(IMAGE_PATTERN, reference)), "RSI_SWE_IMAGE_REFERENCE")
    info = json.loads(await docker_command("image", "inspect", reference))[0]
    require(reference in info.get("RepoDigests", []), "RSI_SWE_IMAGE_CHANGED")
    return info["Id"]


def canonical_archive(raw):
    records, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
        for member in bundle:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "RSI_ARCHIVE_PATH")
            if not path.parts or member.isdir() or member.issym() or member.islnk():
                continue
            require(".git" not in path.parts and member.isfile(), "RSI_PROJECT_SPECIAL_FILE")
            name = str(path)
            require(name not in records and member.size <= 20_000_000, "RSI_INPUT_TOO_LARGE")
            total += member.size
            require(total <= MAX_PROJECT_BYTES and len(records) < 20000, "RSI_INPUT_TOO_LARGE")
            with bundle.extractfile(member) as stream:
                data = stream.read(member.size + 1)
            require(len(data) == member.size)
            records[name] = (data, member.mode & 0o100)
    result = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=result, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as bundle,
    ):
        for name, (data, executable) in sorted(records.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600 | executable
            bundle.addfile(info, io.BytesIO(data))
    return result.getvalue()


async def import_swe(row, *, revision):
    from roami_agent.improvement.evaluation.execution.containers import docker_command

    require(row["instance_id"] in TASKS and bool(re.fullmatch(r"[a-f0-9]{40}", revision)))
    require(bool(re.fullmatch(r"[a-f0-9]{40}", row["base_commit"])))
    image = row["image"]
    require(bool(re.fullmatch(r"swebench/sweb\.eval\.x86_64\.[a-z0-9_-]+:latest", image)))
    detail = json.loads(await docker_command("image", "inspect", image))[0]
    references = [r for r in detail["RepoDigests"] if re.fullmatch(IMAGE_PATTERN, r)]
    require(len(references) == 1, "RSI_SWE_IMAGE_REQUIRED")
    reference = references[0]
    image_id = await resolve_image(reference)
    name = "roami-rsi-source-" + secrets.token_hex(8)
    await docker_command(
        "create",
        "--name",
        name,
        "--label",
        "roami.rsi=" + name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "0:0",
        "--entrypoint",
        "tar",
        image_id,
        "--exclude=.git",
        "--exclude=__pycache__",
        "--exclude=*.pyc",
        "--exclude=.pytest_cache",
        "-czf",
        "-",
        "-C",
        "/testbed",
        ".",
    )
    try:
        archive = canonical_archive(
            await docker_command("start", "--attach", name, timeout=180, maximum=64_000_000)
        )
    finally:
        from roami_agent.improvement.evaluation.execution.containers import remove_container

        await remove_container(name, name)
    prefix, test_file = TASKS[row["instance_id"]]
    cases = {
        f"source-{i // 8_000_000:03}.tgz.part": base64.b64encode(
            archive[i : i + 8_000_000]
        ).decode()
        for i in range(0, len(archive), 8_000_000)
    }
    require(len(archive) <= 56_000_000, "RSI_INPUT_TOO_LARGE")
    case = {
        "id": "swe_verified:" + row["instance_id"],
        "category": "CODE",
        "layer": "public_agent",
        "split": "public_test",
        "cluster": "swe_verified:" + row["repo"],
        "counts_as_delivery": True,
        "prompt": row["problem_statement"]
        + "\n\nThe frozen repository is prepared in /workspace/project with a clean local Git baseline (upstream future history removed). Native project Python is available through `python /workspace/project-python.py ARGS`; for example `python /workspace/project-python.py -m pytest -q "
        + test_file
        + "`. It uses the frozen upstream environment, no network, and a read-only snapshot of your current project. The Roami container default Python is NOT the project interpreter. Use cwd=/workspace for shell calls; edit project files, run native tests, then save `git -C /workspace/project diff --binary` to /workspace/prediction.patch. Only production .py changes under "
        + prefix
        + " are accepted; tests/configuration are frozen. Hidden tests and reference patches remain outside the Agent. This adapted task is not an official leaderboard result.",
        "files": {"project-python.py": CLIENT},
        "asset_files": cases,
        "limits": {"seconds": 1800, "tokens": 512000, "requests": 64},
        "judge": {
            "kind": "swe",
            "instance_id": row["instance_id"],
            "image": reference,
            "base_commit": row["base_commit"],
            "archive_sha256": hashlib.sha256(archive).hexdigest(),
            "archive_parts": sorted(cases),
            "test_patch": row["test_patch"],
            "test_file": test_file,
            "production_prefix": prefix,
            "fail_to_pass": row["FAIL_TO_PASS"],
            "pass_to_pass": row["PASS_TO_PASS"],
        },
        "origin": {
            "benchmark": "swe_verified",
            "task_id": row["instance_id"],
            "revision": revision,
            "source_split": "test",
            "input_sha256": digest(
                {
                    "prompt": row["problem_statement"],
                    "source_sha256": hashlib.sha256(archive).hexdigest(),
                    "image": reference,
                }
            ),
            "base_commit": row["base_commit"],
            "runtime_image": reference,
            "adapter_revision": "native-project-snapshot-v1",
            "adapted": True,
            "adaptation": "Frozen upstream image and project interpreter; clean source snapshot without future Git history; native tests through a scoped broker; original held-out test patch and required pass lists, no dependency reinstall. Not official environment-comparable.",
        },
    }
    return freeze_suite(
        "swe-" + row["instance_id"] + "-v1", [case], official_leaderboard_comparable=False
    )


def prepare_project(case, workspace):
    spec = case["judge"]
    archive = b"".join(
        base64.b64decode(case["asset_files"][p], validate=True) for p in spec["archive_parts"]
    )
    require(hashlib.sha256(archive).hexdigest() == spec["archive_sha256"], "RSI_SOURCE_CHANGED")
    result = unpack_project(archive, workspace / "project")
    for part in spec["archive_parts"]:
        relative_file(workspace, part).unlink()
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="RSI",
        GIT_AUTHOR_EMAIL="rsi@invalid",
        GIT_COMMITTER_NAME="RSI",
        GIT_COMMITTER_EMAIL="rsi@invalid",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    for args in [
        ("init", "-q", "-b", "main"),
        ("add", "-f", "-A"),
        ("commit", "-qm", "Frozen source"),
    ]:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
            cwd=workspace / "project",
            env=environment,
            check=True,
            capture_output=True,
            timeout=60,
        )
    return result


def patch_paths(patch, prefix):
    names = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/([^ ]+) b/([^ ]+)", line)
            require(match is not None and match[1] == match[2], "RSI_PATCH_PATH")
            path = PurePosixPath(match[1])
            require(
                ".." not in path.parts
                and str(path).startswith(prefix)
                and path.suffix == ".py"
                and "tests" not in path.parts
                and path.name != "conftest.py",
                "RSI_PATCH_PATH",
            )
            names.append(str(path))
        if line.startswith(("--- ", "+++ ")):
            require(
                line[4:] in {"/dev/null", *("a/" + n for n in names), *("b/" + n for n in names)},
                "RSI_PATCH_PATH",
            )
    require(not patch.strip() or bool(names), "RSI_PATCH_PATH")
    return names


def parse_test_statuses(output):
    statuses = {}
    for line in re.sub(r"\x1b\[[0-9;]*m", "", output).splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)", line)
        if match:
            statuses.setdefault(match[2], set()).add(match[1])
    return statuses


async def grade_swe(case, workspace, executor):
    from roami_agent.improvement.evaluation.execution.containers import docker_command

    spec = case["judge"]
    path = relative_file(workspace, "prediction.patch")
    require(path.is_file() and path.stat().st_size <= 200000, "RSI_ARTIFACT_UNAVAILABLE")
    patch = path.read_text()
    names = patch_paths(patch, spec["production_prefix"])
    image_id = await resolve_image(spec["image"])
    name = "roami-rsi-swe-grade-" + secrets.token_hex(8)
    script = """set -euo pipefail
exec 2>&1
source /opt/miniconda3/bin/activate testbed
cd /testbed
git reset --hard BASE
if [ -s /tmp/prediction.patch ]; then git apply --check /tmp/prediction.patch; git apply /tmp/prediction.patch; fi
git checkout BASE -- TEST_FILE
git apply /tmp/frozen-tests.patch
set +e
python --version
python -m pytest -rA -p no:cacheprovider TEST_FILE
code=$?
printf "RSI_PYTEST_EXIT:%s\\n" "$code"
exit 0
""".replace("BASE", spec["base_commit"]).replace("TEST_FILE", spec["test_file"])
    setup = (
        "printf '%s' '"
        + base64.b64encode(patch.encode()).decode()
        + "' | base64 -d > /tmp/prediction.patch\nprintf '%s' '"
        + base64.b64encode(spec["test_patch"].encode()).decode()
        + "' | base64 -d > /tmp/frozen-tests.patch\n"
    )
    await docker_command(
        "create",
        "--interactive",
        "--name",
        name,
        "--label",
        "roami.rsi=" + name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "4g",
        "--cpus",
        "2",
        "--pids-limit",
        "256",
        "--entrypoint",
        "/bin/bash",
        image_id,
    )
    try:
        output = (
            await docker_command(
                "start",
                "--attach",
                "--interactive",
                name,
                input=(setup + script).encode(),
                timeout=600,
            )
        ).decode(errors="replace")
    finally:
        await executor.remove(name, name)
    statuses = parse_test_statuses(output)
    checks = {
        key: all(statuses.get(test) == {"PASSED"} for test in spec[key])
        for key in ("fail_to_pass", "pass_to_pass")
    }
    checks["production_patch"] = bool(names)
    passed = all(checks.values())
    return {
        **quality(dict.fromkeys(DIMENSIONS, 3 if passed else 0), hard_passed=passed),
        "native_metric": float(passed),
        "checks": checks,
        "test_statuses": {
            key: sorted(statuses.get(key, []))
            for key in spec["fail_to_pass"] + spec["pass_to_pass"]
        },
        "evidence": [
            {"path": "prediction.patch", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ],
        "verifier_output": output[-200000:],
        "verifier_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "grade_scope": "native_upstream_required_tests_with_frozen_test_patch",
        "official_leaderboard_comparable": False,
        "runtime_image": image_id,
    }
