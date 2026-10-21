#!/usr/bin/env python3
"""Bind development commands to a recorded, private tmux server."""

import fcntl
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def query(binary, socket, *args, env=None):
    return subprocess.run(
        [binary, "-f", os.devnull, "-S", str(socket), *args],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def identity(state):
    result = query(
        state["binary"],
        state["socket"],
        "display-message",
        "-p",
        "#{pid}\t#{@roami_test_instance}",
    )
    if result.returncode:
        if any(
            message in result.stderr
            for message in (
                "no server running",
                "No such file or directory",
                "Connection refused",
            )
        ):
            return None
        raise RuntimeError(
            "Cannot verify isolated tmux server: " + result.stderr.strip()
        )
    pid, token = result.stdout.strip().split("\t", 1)
    if token != state["token"] or pid != state["pid"]:
        raise RuntimeError("Isolated tmux server identity changed; refusing access")
    return pid


def main():
    if len(sys.argv) < 3:
        raise ValueError(
            "Usage: isolated-roami.sh <instance-directory> <command...|--stop>"
        )
    requested = Path(sys.argv[1]).absolute()
    if requested.is_symlink():
        raise ValueError("Instance directory must not be a symlink")
    root = requested.resolve()
    production = Path.home() / ".roami"
    if (
        root in (Path("/"), Path.home(), Path(tempfile.gettempdir()))
        or root == production
        or production in root.parents
    ):
        raise ValueError("Use a dedicated test directory outside the production home")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid():
        raise ValueError("Instance directory belongs to another user")
    root.chmod(0o700)
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:24]
    sockets = Path(tempfile.gettempdir()) / ("roami-test-sockets-" + str(os.getuid()))
    if sockets.is_symlink():
        raise ValueError("Test socket directory must not be a symlink")
    sockets.mkdir(mode=0o700, exist_ok=True)
    if sockets.stat().st_uid != os.getuid():
        raise ValueError("Test socket directory belongs to another user")
    sockets.chmod(0o700)
    socket = sockets / (digest + ".sock")
    manifest = root / "tmux-instance.json"
    stopping = sys.argv[2:] == ["--stop"]
    verifying = sys.argv[2:] == ["--verify"]
    env = dict(os.environ)
    for prefix in ("ROAMI", "ROAM", "TTMUX"):
        for suffix in ("HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"):
            env.pop(prefix + "_" + suffix, None)
    for key in ("TMUX", "TMUX_PANE", "TMUX_TMPDIR", "TMUX_BIN", "TTMUX_BIN"):
        env.pop(key, None)
    env.update(
        ROAMI_HOME=str(root),
        ROAMI_DATA=str(root),
        ROAMI_CONFIG=str(root / "config.yaml"),
        ROAMI_DATABASE_DIR=str(root / "database"),
        ROAMI_BACKUP_DIR=str(root / "backups"),
    )
    with (root / "tmux-instance.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if manifest.exists():
            state = json.loads(manifest.read_text())
            if state["root"] != str(root) or state["socket"] != str(socket):
                raise ValueError("Instance manifest does not match this test directory")
            if (
                not isinstance(state["pid"], str)
                or not state["pid"].isdigit()
                or int(state["pid"]) <= 0
            ):
                raise ValueError("Instance manifest has no valid server PID")
        else:
            if stopping or verifying:
                raise ValueError("No recorded test instance; refusing cleanup")
            if socket.exists():
                raise ValueError("Unrecorded socket already exists; refusing adoption")
            binary = shutil.which("tmux")
            if not binary:
                raise ValueError("tmux is required for isolated validation")
            state = {
                "root": str(root),
                "socket": str(socket),
                "binary": binary,
                "token": secrets.token_hex(16),
                "pid": "",
            }
        pid = identity(state) if state["pid"] else None
        if verifying:
            print("Verified recorded test tmux instance: " + str(root))
            return
        if stopping:
            if pid:
                result = query(state["binary"], socket, "kill-server")
                if result.returncode:
                    raise RuntimeError(result.stderr.strip())
            print("Stopped recorded test tmux instance: " + str(root))
            return
        if not pid:
            result = query(
                state["binary"],
                socket,
                "new-session",
                "-d",
                "-s",
                "_roami-test",
                env=env,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            result = query(
                state["binary"],
                socket,
                "set-option",
                "-g",
                "@roami_test_instance",
                state["token"],
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            result = query(state["binary"], socket, "display-message", "-p", "#{pid}")
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            state["pid"] = result.stdout.strip()
            manifest.write_text(json.dumps(state) + "\n")
            manifest.chmod(0o600)
        wrapper = root / "tmux"
        wrapper.write_text(
            "#!/bin/sh\nexec "
            + shlex.quote(state["binary"])
            + " -f "
            + shlex.quote(os.devnull)
            + " -S "
            + shlex.quote(str(socket))
            + ' "$@"\n'
        )
        wrapper.chmod(0o700)
    # Raw tmux in tests inherits the private socket, even if TMUX_TMPDIR changes.
    env.update(TMUX_BIN=str(wrapper), TMUX=str(socket) + "," + state["pid"] + ",0")
    private_tmp = Path(tempfile.gettempdir()) / (
        "rt" + str(os.getuid()) + "-" + digest[:8]
    )
    if private_tmp.is_symlink():
        raise ValueError("Test temporary directory must not be a symlink")
    private_tmp.mkdir(mode=0o700, exist_ok=True)
    if private_tmp.stat().st_uid != os.getuid():
        raise ValueError("Test temporary directory belongs to another user")
    private_tmp.chmod(0o700)
    env["TMUX_TMPDIR"] = str(private_tmp)
    os.execvpe(sys.argv[2], sys.argv[2:], env)


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print("isolated-roami: " + str(error), file=sys.stderr)
        sys.exit(1)
