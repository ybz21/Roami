"""Record the complete target-specific runtime, with no build-machine venv paths."""

import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

package, python_exe, version, target, commit = sys.argv[1:]
root = Path(package)
runtime = root / "runtime"
# Dereference interpreter symlinks so the release never contains external link targets.
shutil.copytree(Path(python_exe).parent.parent, runtime / "python", symlinks=False)
requirements = runtime / "requirements.txt"
wheels = sorted((runtime / "wheels").glob("*.whl"))
assert any(wheel.name.startswith("roami_agent-") for wheel in wheels)
pins = []
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        distribution = Parser().parsestr(archive.read(metadata).decode())
        pins.append(
            f"{distribution['Name']}=={distribution['Version']} "
            f"--hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}"
        )
        if target == "darwin-amd64" and distribution["Name"] == "cryptography":
            with tempfile.TemporaryDirectory() as temporary:
                for member in archive.namelist():
                    if not member.endswith(".so"):
                        continue
                    library = Path(temporary) / Path(member).name
                    library.write_bytes(archive.read(member))
                    linked = subprocess.check_output(["otool", "-L", str(library)], text=True)
                    identity = subprocess.check_output(["otool", "-D", str(library)], text=True)
                    own_names = {line.strip() for line in identity.splitlines()[1:]}
                    for dependency in linked.splitlines()[1:]:
                        name = dependency.strip().split(" (", 1)[0]
                        if name in own_names:
                            continue
                        if not name.startswith(("/usr/lib/", "/System/Library/")):
                            raise ValueError(f"Non-system cryptography dependency: {name}")
# Source inputs were lock/hash checked by pip; installation pins the resulting target wheels.
requirements.write_text("\n".join(pins) + "\n")
# Schema is release metadata, never inferred from a user's live database.
schema_ast = ast.parse(Path("agent-runtime/src/roami_agent/storage/migrations.py").read_text())
schema_version = next(
    ast.literal_eval(node.value)
    for node in schema_ast.body
    if isinstance(node, ast.Assign)
    and any(isinstance(name, ast.Name) and name.id == "SCHEMA_VERSION" for name in node.targets)
)
license_dir = root / "licenses"
license_dir.mkdir(exist_ok=True)
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
