"""Offline tools must stay available when an agent explicitly uses a login shell."""

import json
import os
import shlex
import subprocess

import pytest


@pytest.mark.parametrize("shell", ["python", "python3", "bash", "bash-login"])
def test_offline_python_tools_survive_shell_selection(shell):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE for the real offline execution environment")
    program = (
        "import importlib.util,json,os,sys;"
        "print(json.dumps({'prefix':sys.prefix,'home':os.environ.get('HOME'),"
        "'xdg':os.environ.get('XDG_CONFIG_HOME'),'modules':{"
        "m:importlib.util.find_spec(m)is not None for m in "
        "['pptx','lxml','PIL','numpy','scipy','openpyxl','playwright']}}))"
    )
    command = (
        ["bash", "-lc" if shell == "bash-login" else "-c", "python3 -c " + shlex.quote(program)]
        if shell.startswith("bash")
        else [shell, "-c", program]
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            "HOME=/tmp/roami-home",
            "--env",
            "XDG_CONFIG_HOME=/tmp/roami-config",
            "--entrypoint",
            command[0],
            image,
            *command[1:],
        ],
        text=True,
        capture_output=True,
        timeout=25,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["prefix"] == "/opt/roami-agent/.venv", observed
    assert all(observed["modules"].values()), observed
    assert observed["home"] == "/tmp/roami-home"
    assert observed["xdg"] == "/tmp/roami-config"
