"""Run the public report regression in a caller-supplied offline image."""

import argparse
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def snapshot(repository):
    paths = [
        repository / "skills/market-series-report",
        Path(__file__).resolve().parents[1],
    ]
    return {
        str(p.relative_to(repository)): hashlib.sha256(p.read_bytes()).hexdigest()
        for root in paths
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and ".ruff_cache" not in p.parts
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]
    repository = folder.parents[1]
    output = args.output.resolve()
    if output == repository or output.is_relative_to(repository):
        parser.error("Output must be a new directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    frozen = snapshot(repository)
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    # Resolve the local ID first: validation must not pull an unreviewed image.
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True
    ).strip()
    launcher = repository / "scripts/dev/isolated-roami.sh"
    with (output / "tests.log").open("w") as log:
        try:
            result = subprocess.run(
                [
                    str(launcher),
                    str(output / "instance"),
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--env",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "--env",
                    "HOME=/tmp",
                    "--mount",
                    f"type=bind,src={repository},dst=/workspace,readonly",
                    "--mount",
                    f"type=bind,src={output},dst=/evidence",
                    "--workdir",
                    "/workspace",
                    "--entrypoint",
                    "python",
                    image,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp=/evidence/tmp",
                    "--junitxml=/evidence/tests.xml",
                    "skills/market-series-report/tests",
                ],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        finally:
            cleanup = subprocess.run(
                [str(launcher), str(output / "instance"), "--stop"],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )
            (output / "cleanup.log").write_text(cleanup.stdout + cleanup.stderr)
    suites = ET.parse(output / "tests.xml").getroot()
    tests = list(suites.iter("testcase"))
    failed = sum(
        any(t.find(tag) is not None for tag in ("failure", "error", "skipped"))
        for t in tests
    )
    expected = json.loads((folder / "tools.json").read_text())["expected_tests"]
    unchanged = snapshot(repository) == frozen
    passed = (
        result.returncode == cleanup.returncode == failed == 0
        and len(tests) == expected
        and unchanged
    )
    receipt = {
        "case": "MECH-MP01",
        "passed": passed,
        "tests": len(tests),
        "failed_or_skipped": failed,
        "source_unchanged": unchanged,
        "local_image": image,
        "external_model_calls": 0,
        "historical_suite_updated": False,
        "visual_inspection_performed": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
