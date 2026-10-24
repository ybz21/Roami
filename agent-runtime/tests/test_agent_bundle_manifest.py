import runpy
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build/agent-bundle-manifest.py"


@pytest.mark.parametrize("external", [False, True])
def test_intel_wheel_distinguishes_its_identity_from_external_libraries(
    tmp_path, monkeypatch, external
):
    package = tmp_path / "release"
    wheels = package / "runtime/wheels"
    wheels.mkdir(parents=True)
    python = tmp_path / "source-python/bin/python3"
    python.parent.mkdir(parents=True)
    python.write_text("interpreter fixture")
    for name, version in (("roami_agent", "0.1.0"), ("cryptography", "50.0.2")):
        with zipfile.ZipFile(wheels / f"{name}-{version}-py3-none-any.whl", "w") as archive:
            archive.writestr(
                f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n"
            )
            if name == "cryptography":
                archive.writestr("cryptography/hazmat/bindings/_rust.abi3.so", "library fixture")

    identity = "@rpath/cryptography.hazmat.bindings._rust.abi3.so"

    def otool(argv, *, text):
        assert argv[0] == "otool" and text
        if argv[1] == "-D":
            return f"{argv[2]}:\n{identity}\n"
        assert argv[1] == "-L"
        names = [identity, "/usr/lib/libSystem.B.dylib"]
        if external:
            names.append("@rpath/libcrypto.3.dylib")
        return f"{argv[2]}:\n" + "".join(
            f"\t{name} (compatibility version 1.0.0, current version 1.0.0)\n" for name in names
        )

    monkeypatch.setattr("subprocess.check_output", otool)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), str(package), str(python), "dev", "darwin-amd64", "test"]
    )
    if external:
        with pytest.raises(
            ValueError, match="Non-system cryptography dependency: @rpath/libcrypto"
        ):
            runpy.run_path(str(SCRIPT), run_name="__main__")
    else:
        runpy.run_path(str(SCRIPT), run_name="__main__")
        assert (
            "cryptography==50.0.2 --hash=sha256:"
            in (package / "runtime/requirements.txt").read_text()
        )
        assert (package / "manifest.json").is_file()
