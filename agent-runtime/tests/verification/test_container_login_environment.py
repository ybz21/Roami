"""The host build installs the login environment and keeps Case runtime selectors valid."""

import json
import subprocess
from pathlib import Path


def test_container_installs_login_environment_and_documents_slide_case_checks():
    runtime = Path(__file__).parents[2]
    dockerfile = (runtime / "improvement.Dockerfile").read_text()
    assert "COPY scripts/container-runtime-path.sh /etc/profile.d/roami-runtime.sh" in dockerfile
    profile = runtime / "scripts/container-runtime-path.sh"
    subprocess.run(["sh", "-n", str(profile)], check=True)
    for case in ["case-52-public-12", "case-53-public-13"]:
        materials = json.loads((runtime.parent / "cases" / case / "materials.json").read_text())
        checks = materials["tools"]["runtime_checks"]
        assert checks["pytest_selector"] == (
            "tests/test_rsi_login_environment.py::test_offline_python_tools_survive_shell_selection"
        )
        assert checks["image_label"] == {"org.roami.rsi.login-runtime-path": "1"}
