"""Keep RSI dependencies directed and ledger SQL below its workflow and API layers."""

import ast
from pathlib import Path

from roami_agent.improvement.evaluation.comparison_context import grading_hash, grading_sources

ROOT = Path(__file__).parents[1] / "src/roami_agent/improvement"
LAYERS = {
    "domain": 0,
    "integrations": 1,
    "evaluation": 2,
    "persistence": 3,
    "workflows": 4,
    "presentation": 5,
    "service.py": 6,
    "entrypoints": 7,
    "cli.py": 7,
    "container_agent.py": 7,
    "import_diagnostic.py": 7,
    "__init__.py": 7,
}


def test_dependencies_do_not_point_up_into_workflows_views_or_composition():
    violations = []
    for path in ROOT.rglob("*.py"):
        layer = path.relative_to(ROOT).parts[0]
        assert layer in LAYERS, f"Unclassified RSI module: {path}"
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                if not name.startswith("roami_agent.improvement."):
                    continue
                target = name.split(".")[2]
                target = "service.py" if target == "service" else target
                if LAYERS[target] > LAYERS[layer]:
                    violations.append((str(path.relative_to(ROOT)), node.lineno, name))
    assert not violations, violations


def test_workflows_and_api_views_do_not_execute_ledger_sql():
    violations = []
    for folder in ("domain", "integrations", "workflows", "presentation"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                sql_call = (
                    node.func.attr == "execute"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.lstrip().split(" ", 1)[0].upper()
                    in {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "BEGIN", "PRAGMA"}
                )
                if node.func.attr in {"connection", "executemany", "executescript"} or sql_call:
                    violations.append((str(path.relative_to(ROOT)), node.lineno))
    assert not violations, violations


def test_domain_rules_do_not_read_files_or_import_runtime_adapters():
    forbidden = {"sqlite3", "httpx", "asyncio", "os", "subprocess", "pathlib"}
    for path in (ROOT / "domain").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(name.split(".")[0] in forbidden for name in names), path
            assert not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ), path


def test_grading_identity_includes_extracted_scoring_and_benchmark_rules(monkeypatch):
    sources = grading_sources()
    assert {
        "domain/scoring.py",
        "evaluation/authored_grading.py",
        "evaluation/benchmarks/spreadsheet.py",
    } <= sources.keys()
    suite = {"cases": [{"id": "fixture", "judge": {"kind": "numeric", "expected": 1}}]}
    before = grading_hash(suite, object())
    monkeypatch.setattr(
        "roami_agent.improvement.evaluation.comparison_context.grading_sources",
        lambda: {**sources, "domain/scoring.py": "changed-scoring"},
    )
    assert grading_hash(suite, object()) != before


def test_api_views_do_not_start_work_or_update_research_projections():
    forbidden = {"sync_research", "begin_request", "capture_request", "freeze_cases", "set_state"}
    for path in (ROOT / "presentation").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden, (path, node.lineno)


def test_container_recipe_excludes_the_relocated_host_fixture_and_answer_modules():
    dockerfile = (ROOT.parents[2] / "improvement.Dockerfile").read_text()
    removal = dockerfile.split("RUN rm -f ", 1)[1].split("\nRUN ", 1)[0]
    for name in ("authored_fixtures", "corpus", "authored_grading"):
        path = f"src/roami_agent/improvement/evaluation/{name}.py"
        assert path in removal
        assert (ROOT / "evaluation" / f"{name}.py").is_file()
    assert "ROAMI_RSI_CONTAINER_BUILD=1" in dockerfile
