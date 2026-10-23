"""Record the complete target-specific runtime, with no build-machine venv paths."""

import ast
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

package, python_exe, version, target, commit = sys.argv[1:]
root = Path(package)
runtime = root / "runtime"
# Dereference interpreter symlinks so the release never contains external link targets.
shutil.copytree(Path(python_exe).parent.parent, runtime / "python", symlinks=False)
requirements = runtime / "requirements.txt"
wheel = next((runtime / "wheels").glob("roami_agent-*.whl"))
project = tomllib.loads((runtime / "pyproject.toml").read_text())
with requirements.open("a") as output:
    output.write(
        "\nroami-agent=="
        + project["project"]["version"]
        + " --hash=sha256:"
        + hashlib.sha256(wheel.read_bytes()).hexdigest()
        + "\n"
    )
# Schema is release metadata, never inferred from a user's live database.
schema_ast = ast.parse(Path("agent-runtime/src/roami_agent/storage/migrations.py").read_text())
schema_version = next(
    ast.literal_eval(node.value)
    for node in schema_ast.body
    if isinstance(node, ast.Assign)
    and any(isinstance(name, ast.Name) and name.id == "SCHEMA_VERSION" for name in node.targets)
)
license_dir = root / "licenses"
license_dir.mkdir()
for filename in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
    if Path(filename).is_file():
        shutil.copy2(filename, license_dir / filename)
python_licenses = runtime / "python" / "licenses"
if python_licenses.is_dir():
    shutil.copytree(python_licenses, license_dir / "python")
files = {
    str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(root.rglob("*"))
    if path.is_file()
}
manifest = {
    "format": 1,
    "version": version,
    "target": target,
    "python": sys.version.split()[0],
    "schema": schema_version,
    "commit": commit,
    "files": files,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
