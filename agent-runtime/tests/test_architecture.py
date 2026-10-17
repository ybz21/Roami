"""Enforce the approved runtime dependency boundaries as implementation grows."""

import ast
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "roami_agent"


def test_core_depends_only_on_protocol_and_standard_library():
    for path in (SOURCE / "core").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not node.level, f"Use explicit imports to audit the core boundary: {path}"
                module = node.module or ""
                assert (
                    module.startswith("roami_agent.protocol.")
                    or module.split(".")[0] in sys.stdlib_module_names
                ), (path, module)
            elif isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names
                ), path
            elif isinstance(node, ast.Attribute):
                assert node.attr not in {"execute", "executemany", "executescript"}, path


def test_protocol_does_not_depend_on_application_or_adapters():
    for path in (SOURCE / "protocol").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("roami_agent.")
            ):
                assert node.module.startswith("roami_agent.protocol."), (path, node.module)


def test_http_routes_do_not_query_storage_or_import_the_composition_root():
    tree = ast.parse((SOURCE / "server" / "http.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "roami_agent.app"
            assert not (node.module or "").startswith("roami_agent.storage.")
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"execute", "executemany", "executescript"}
            if node.attr == "call":
                assert not isinstance(node.value, ast.Attribute) or node.value.attr != "db"
