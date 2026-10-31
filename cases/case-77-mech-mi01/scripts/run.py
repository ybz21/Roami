"""Freeze and run role-scoped Main file images with local model events."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    case = Path(__file__).resolve().parents[1]
    repository = case.parents[1]
    if output == repository or repository in output.parents:
        parser.error("Output must be a new directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    tools = json.loads((case / "tools.json").read_text())
    assert (case / "input/image.json").read_bytes() == (
        repository / "agent-runtime/tests/fixtures/main-file-image.json"
    ).read_bytes()
    files = {
        path
        for folder in (
            case,
            repository / "agent-runtime/src",
            repository / "agent-runtime/tests",
        )
        for path in folder.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    files.update(repository / name for name in tools["pytest_selectors"])
    frozen = {str(path.relative_to(repository)): digest(path) for path in sorted(files)}
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    launcher = repository / "scripts/dev/isolated-roami.sh"
    instance = output / "instance"
    with (
        tempfile.TemporaryDirectory(prefix="roami-mi-") as scratch,
        (output / "tests.log").open("w") as log,
    ):
        try:
            result = subprocess.run(
                [
                    str(launcher),
                    str(instance),
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-o",
                    "xfail_strict=true",
                    "--junitxml",
                    str(output / "junit.xml"),
                    "--basetemp",
                    str(Path(scratch) / "pytest"),
                    *tools["pytest_selectors"],
                ],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        finally:
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=repository,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
    suites = ET.parse(output / "junit.xml").getroot().iter("testsuite")
    counts = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib[key])
    unchanged = all(digest(repository / name) == sha for name, sha in frozen.items())
    passed = (
        result.returncode == cleanup.returncode == 0
        and unchanged
        and counts
        == {
            "tests": tools["expected_collected"],
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
    )
    receipt = {
        "case": "MECH-MI01",
        "passed": passed,
        "tests": counts,
        "exit_code": result.returncode,
        "cleanup_exit_code": cleanup.returncode,
        "implementation_unchanged": unchanged,
        "model_calls": 0,
        "historical_suite_updated": False,
        "scope": "saved role image permissions and real Main file pixels; not video selection quality",
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
