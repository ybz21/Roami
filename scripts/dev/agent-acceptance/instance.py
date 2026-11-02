#!/usr/bin/env python3
"""Create or stop a private acceptance server without touching production sessions."""

import argparse
import http.cookiejar
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from workflow_skills import install_workflow_skills

REPO = Path(__file__).resolve().parents[3]


def stop(state_path):
    state = json.loads(state_path.read_text())
    root = Path(state["root"])
    if not str(root).startswith("/tmp/roami-acceptance-20261019-") or not state[
        "namespace"
    ].startswith("roami-acceptance-20261019-"):
        raise ValueError("Not an acceptance instance")
    launcher = ["bash", str(REPO / "scripts/dev/isolated-roami.sh"), str(root)]
    subprocess.run([*launcher, "--verify"], check=True, capture_output=True)
    for key in ["webPid", "agentPid"]:
        pid = state[key]
        try:
            env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            if ("ROAMI_HOME=" + str(root)).encode() not in env or os.getpgid(
                pid
            ) != pid:
                raise ValueError("Process identity no longer matches")
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass
    subprocess.run([*launcher, "--stop"], check=True, capture_output=True)
    print("Stopped only the isolated acceptance process groups and tmux socket")


def start(args):
    binary = str(Path(args.cli).resolve())
    source = Path(args.config_root).expanduser().resolve()
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    namespace = "roami-acceptance-20261019-" + stamp
    root = Path("/tmp") / namespace
    root.mkdir(mode=0o700)
    for directory in ["logs", "workspaces", "agents", "bin"]:
        (root / directory).mkdir(mode=0o700)
    shutil.copy2(binary, root / "bin/roami")
    binary = str(root / "bin/roami")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    model = tomllib.loads((source / "agent.toml").read_text())["model"]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ROAMI_", "ROAM_", "TTMUX_", "GIT_"))
        and key not in {"TMUX", "TMUX_PANE", "TMUX_BIN", "TMUX_TMPDIR"}
    }
    names = {
        model.get("key_env", "ROAMI_AGENT_API_KEY"),
        "ROAMI_AGENT_SAVED_MAIN_KEY",
        "ROAMI_AGENT_SAVED_WORKER_KEY",
    }
    env.update({key: value for key, value in os.environ.items() if key in names})
    service_env = source / "agent-service.env"
    if service_env.exists():
        for line in service_env.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in names:
                env[key] = value.strip().strip('"').strip("'")
    env.update(
        ROAMI_HOME=str(root),
        ROAMI_DATA=str(root),
        ROAMI_CONFIG=str(root / "config.yaml"),
        ROAMI_AGENT_RUNTIME=str(REPO / "agent-runtime"),
        ROAMI_AGENT_CLI=binary,
        PATH=str(root / "bin") + os.pathsep + env.get("PATH", ""),
    )
    launcher = ["bash", str(REPO / "scripts/dev/isolated-roami.sh"), str(root)]
    password = secrets.token_urlsafe(24)
    config = root / "config.yaml"
    config.write_text(
        "web:\n  bind: 127.0.0.1:"
        + str(port)
        + "\n  tls: false\n  password: "
        + json.dumps(password)
        + "\n"
    )
    config.chmod(0o600)
    settings = "[model]\n" + "\n".join(
        key + "=" + json.dumps(value)
        for key, value in model.items()
        if key in {"endpoint", "name", "key_env", "worker"}
    )
    parameters = dict(model.get("parameters", {}))
    if args.main_reasoning_effort:
        parameters["reasoning_effort"] = args.main_reasoning_effort
    if parameters:
        settings += (
            "\n[model.parameters]\n"
            + "\n".join(
                key + "=" + json.dumps(value) for key, value in parameters.items()
            )
            + "\n"
        )
    if args.main_reasoning_effort:
        worker_parameters = model.get("parameters", {})
        settings += (
            "\n[worker.model]\nname="
            + json.dumps(model.get("worker") or model["name"])
            + "\n[worker.model.parameters]\n"
        )
        settings += (
            "\n".join(
                key + "=" + json.dumps(value)
                for key, value in worker_parameters.items()
            )
            + "\n"
        )
    settings += "\n[runtime]\ncoding_directory=" + json.dumps(str(root / "workspaces"))
    skill_markers = {}
    if args.document_skills:
        skills_root, skill_markers = install_workflow_skills(root)
        settings += "\n[tools]\nskill_roots=" + json.dumps([str(skills_root)]) + "\n"
    settings += (
        "\n[tools.browser]\nenabled=true\nendpoint="
        + json.dumps(args.cdp)
        + "\nexisting_tabs=false\nmax_tabs=20\n"
    )
    (root / "agent.toml").write_text(settings)
    saved = source / "agents/model-settings.json"
    if saved.exists():
        shutil.copyfile(saved, root / "agents/model-settings.json")
        (root / "agents/model-settings.json").chmod(0o600)

    def cli(*argv, data=None):
        result = subprocess.run(
            [*launcher, binary, *argv],
            env=env,
            input=data,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
        if result.returncode:
            raise RuntimeError("Acceptance CLI failed: " + argv[0])
        return (
            json.loads(result.stdout)
            if result.stdout.strip().startswith(("{", "["))
            else result.stdout
        )

    processes = []
    try:
        cli("agent", "init", "--runtime-dir", str(REPO / "agent-runtime"))
        for name, argv in [("agent", ["agent", "serve"]), ("web", ["server"])]:
            with (root / "logs" / (name + ".log")).open("wb") as log:
                processes.append(
                    subprocess.Popen(
                        [*launcher, binary, *argv],
                        env=env,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                )
            if name == "agent":
                for _ in range(120):
                    try:
                        cli("agent", "status")
                        break
                    except RuntimeError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Acceptance Agent socket did not become ready")
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def request(path, data=None):
            body = json.dumps(data).encode() if data is not None else None
            with opener.open(
                urllib.request.Request(
                    base + path, data=body, headers={"Content-Type": "application/json"}
                ),
                timeout=10,
            ) as response:
                return json.load(response)

        for _ in range(120):
            try:
                request("/api/version")
                break
            except (OSError, ValueError):
                time.sleep(0.25)
        else:
            raise RuntimeError("Acceptance web server did not start")
        request("/api/login", {"password": password})
        cli(
            "auth",
            "login",
            "--stdin",
            "--json",
            data=json.dumps({"password": password}),
        )
        for _ in range(120):
            try:
                if request("/api/agent/status")["data"]["configured"]:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("Acceptance Agent did not start")
        project = root / "workspaces/existing-project"
        project.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main", str(project)], check=True, capture_output=True
        )
        (project / "README.md").write_text("Isolated dispatch acceptance fixture\n")
        subprocess.run(
            ["git", "-C", str(project), "add", "README.md"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "-c",
                "user.name=Acceptance",
                "-c",
                "user.email=acceptance@example.invalid",
                "commit",
                "-m",
                "initial",
            ],
            check=True,
            capture_output=True,
        )
        remote = root / "workspaces/fixture-origin.git"
        subprocess.run(
            ["git", "clone", "--bare", str(project), str(remote)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "remote", "add", "origin", str(remote)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "fetch", "origin"],
            check=True,
            capture_output=True,
        )
        registered = cli(
            "project", "create", str(project), "--name", "派活验收项目", "--json"
        )
        state = {
            "root": str(root),
            "base": base,
            "namespace": namespace,
            "agentPid": processes[0].pid,
            "webPid": processes[1].pid,
            "projectId": registered["data"]["key"],
            "projectDir": str(project),
            "skillMarkers": skill_markers,
            "cliBin": binary,
        }
        args.state.write_text(json.dumps(state))
        args.state.chmod(0o600)
        cookies = root / "browser-cookies.json"
        cookies.write_text(
            json.dumps(
                [
                    {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path,
                        "secure": c.secure,
                    }
                    for c in jar
                ]
            )
        )
        cookies.chmod(0o600)
        print("Acceptance instance ready; private state:", args.state)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        subprocess.run([*launcher, "--stop"], check=False, capture_output=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--document-skills", action="store_true")
    parser.add_argument("--cli", default=str(REPO / "backend/dist/roami-linux-amd64"))
    parser.add_argument("--config-root", default="~/.roami")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--main-reasoning-effort", choices=["low", "high", "max"])
    args = parser.parse_args()
    if args.stop:
        stop(args.state)
    else:
        start(args)


if __name__ == "__main__":
    main()
