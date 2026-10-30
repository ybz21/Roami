"""Freeze and execute an external Skill package without a provider."""

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    case = Path(__file__).resolve().parents[1]
    repository = case.parents[1]
    if output == repository or repository in output.parents:
        parser.error("Output must be a new directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sys.path.insert(0, str(repository / "skills/presentation-edit/tests"))
    sys.path.insert(0, str(repository / "skills/presentation-edit/scripts"))
    fixture = importlib.import_module("deck_fixture")
    from pptx_package import presentation_metadata

    resources = [
        path
        for path in case.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    implementation = [
        path
        for path in (repository / "agent-runtime/src").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    implementation.extend(
        path
        for path in (repository / "skills/presentation-edit").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    implementation.append(
        repository
        / "agent-runtime/tests/verification/test_presentation_skill_package.py"
    )
    tracked = {
        str(path.relative_to(repository)): digest(path)
        for path in resources + implementation
    }
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    (output / "frozen.json").write_text(
        json.dumps({"head": head, "sha256": tracked}, indent=2) + "\n"
    )
    contract = json.loads((case / "input/recipe.json").read_text())
    body = fixture.deck_bytes(**contract["parameters"])
    (output / "input").mkdir()
    source = output / "input/deck.pptx"
    source.write_bytes(body)
    observed = presentation_metadata(body)
    slide, expected = observed["slides"][0], contract["expected"]
    assert [item["text"] for item in slide["textObjects"]] == expected["drawing_texts"]
    assert slide["topToBottomPaths"] == expected["top_to_bottom_paths"]
    (output / "observed-layout.json").write_text(
        json.dumps(observed, ensure_ascii=False, indent=2) + "\n"
    )
    script = repository / "skills/presentation-edit/scripts/presentation.py"
    request = {
        "path": "input/deck.pptx",
        "expectedSha256": digest(source),
        "destination": "edited.pptx",
        "expectedDestinationSha256": None,
        "operations": [
            {
                "slide": 1,
                "target": {"order": "top_to_bottom", "ordinal": 1},
                "alignment": "center",
            }
        ],
    }
    for label, arguments in [
        ("read", ["inspect", "--path", "input/deck.pptx"]),
        ("edit", ["edit", "--request-json", json.dumps(request)]),
    ]:
        result = subprocess.run(
            [sys.executable, str(script), *arguments, "--workspace", str(output)],
            text=True,
            capture_output=True,
            check=False,
        )
        (output / (label + ".stderr")).write_text(result.stderr)
        (output / (label + "-receipt.json")).write_text(result.stdout)
        assert result.returncode == 0 and json.loads(result.stdout)["ok"] is True
    edited = presentation_metadata((output / "edited.pptx").read_bytes())
    assert edited["slides"][0]["textObjects"][0]["paragraphs"][0]["alignment"] == "left"
    assert (
        edited["slides"][0]["textObjects"][1]["paragraphs"][0]["alignment"] == "center"
    )
    (output / "observed-edited.json").write_text(json.dumps(edited, indent=2) + "\n")
    entry = output / "pytest-entry.py"
    entry.write_text("""import json,sys
from pathlib import Path
import pytest
class Receipt:
 def __init__(self): self.collected=0;self.passed=0;self.skipped=0
 def pytest_collection_finish(self,session): self.collected=len(session.items)
 def pytest_runtest_logreport(self,report):
  uncertain=report.skipped or hasattr(report,"wasxfail")
  if uncertain:self.skipped+=1
  if report.when=="call" and report.passed and not uncertain:self.passed+=1
receipt=Receipt()
result=pytest.main(sys.argv[2:],plugins=[receipt])
Path(sys.argv[1]).write_text(json.dumps(vars(receipt)))
sys.exit(int(result))
""")
    instance = output / "instance"
    launcher = repository / "scripts/dev/isolated-roami.sh"
    with (output / "tests.log").open("w") as log:
        try:
            result = subprocess.run(
                [
                    str(launcher),
                    str(instance),
                    sys.executable,
                    str(entry),
                    str(output / "pytest-receipt.json"),
                    "-q",
                    "--asyncio-mode=auto",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(output / "pytest"),
                    *[
                        str(repository / name)
                        for name in json.loads((case / "tools.json").read_text())[
                            "pytest_selectors"
                        ]
                    ],
                ],
                cwd=repository,
                check=False,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        finally:
            cleanup = subprocess.run(
                [str(launcher), str(instance), "--stop"],
                cwd=repository,
                check=False,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
    receipt = json.loads((output / "pytest-receipt.json").read_text())
    expected_count = json.loads((case / "tools.json").read_text())["expected_collected"]
    unchanged = all(
        digest(repository / name) == value for name, value in tracked.items()
    )
    source_unchanged = source.read_bytes() == body
    passed = (
        result.returncode == 0
        and cleanup.returncode == 0
        and unchanged
        and source_unchanged
        and receipt
        == {"collected": expected_count, "passed": expected_count, "skipped": 0}
    )
    final = {
        "case": "MECH-DP01",
        "passed": passed,
        "tests": receipt,
        "exit_code": result.returncode,
        "cleanup_exit_code": cleanup.returncode,
        "implementation_unchanged": unchanged,
        "input_sha256": digest(source),
        "input_unchanged": source_unchanged,
        "model_calls": 0,
        "historical_suite_updated": False,
        "scope": "external Skill and generic delivery contract, not model acceptance",
    }
    (output / "receipt.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
