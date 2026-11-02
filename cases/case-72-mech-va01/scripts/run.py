"""Freeze the optional video package and exercise real codecs in an offline image."""

import argparse
import hashlib
import json
import os
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default=os.environ.get("ROAMI_RSI_TEST_IMAGE"))
    args = parser.parse_args()
    case = Path(__file__).resolve().parents[1]
    repo = case.parents[1]
    package = repo / "skills/video-assembly"
    output = args.output.resolve()
    if not args.image:
        parser.error("A locally available frozen --image is required")
    if output == repo or repo in output.parents:
        parser.error("Output must be outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    image = subprocess.check_output(
        ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True
    ).strip()
    files = {
        p
        for root in (case, package)
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    frozen = {str(p.relative_to(repo)): digest(p) for p in sorted(files)}
    (output / "frozen.json").write_text(
        json.dumps({"imageId": image, "files": frozen}, indent=2) + "\n"
    )
    launcher = repo / "scripts/dev/isolated-roami.sh"
    instance = output / "instance"
    token = uuid.uuid4().hex
    name = "roami-case-va-" + token
    command = [
        str(launcher),
        str(instance),
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--label",
        "roami.case-token=" + token,
        "--network=none",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        str(package) + ":/repository/skills/video-assembly:ro",
        "-v",
        str(case) + ":/repository/cases/case-72-mech-va01:ro",
        "-v",
        str(output) + ":/proof:rw",
        "--entrypoint",
        "/opt/roami-agent/.venv/bin/python",
        image,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "xfail_strict=true",
        "--junitxml=/proof/junit.xml",
        "/repository/skills/video-assembly/tests",
    ]
    with (output / "tests.log").open("w") as log:
        try:
            result = subprocess.run(
                command, cwd=repo, stdout=log, stderr=subprocess.STDOUT, check=False
            )
        finally:
            found = subprocess.run(
                ["docker", "container", "inspect", name],
                capture_output=True,
                text=True,
                check=False,
            )
            if found.returncode == 0:
                info = json.loads(found.stdout)[0]
                if (
                    info["Config"]["Labels"].get("roami.case-token") != token
                    or info["Image"] != image
                ):
                    raise RuntimeError("Owned container identity changed")
                subprocess.run(
                    ["docker", "rm", "--force", name],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=repo,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
    counts = dict.fromkeys(["tests", "failures", "errors", "skipped"], 0)
    if (output / "junit.xml").is_file():
        for suite in ET.parse(output / "junit.xml").getroot().iter("testsuite"):
            for key in counts:
                counts[key] += int(suite.attrib[key])
    expected = json.loads((case / "tools.json").read_text())["expected_collected"]
    unchanged = all(digest(repo / n) == sha for n, sha in frozen.items())
    passed = (
        result.returncode == cleanup.returncode == 0
        and unchanged
        and counts == {"tests": expected, "failures": 0, "errors": 0, "skipped": 0}
    )
    receipt = {
        "case": "MECH-VA01",
        "passed": passed,
        "tests": counts,
        "exitCode": result.returncode,
        "cleanupExitCode": cleanup.returncode,
        "sourceUnchanged": unchanged,
        "imageId": image,
        "modelCalls": 0,
        "historicalSuiteUpdated": False,
        "scope": "actual codec, timeline and file-publication checks; not visual selection or model quality",
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
