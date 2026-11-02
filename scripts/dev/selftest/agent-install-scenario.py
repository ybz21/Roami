"""Exercise curl-to-bash installation and real daemons without a system Python on PATH."""

import hashlib
import http.cookiejar
import http.server
import io
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
archive = Path(sys.argv[1]).resolve()
assert archive.is_file() and Path(str(archive) + ".sha256").is_file()
root = Path(tempfile.mkdtemp(prefix="roami-install-test-")).resolve()
root.chmod(0o700)
(root / "user-home").mkdir()
launcher = ["bash", str(REPO / "scripts/dev/isolated-roami.sh"), str(root)]
tools = root / "test-tools"
tools.mkdir()
for name in (
    "gzip",
    "bash",
    "sh",
    "awk",
    "sed",
    "head",
    "curl",
    "tar",
    "cp",
    "mv",
    "chmod",
    "mkdir",
    "rm",
    "sleep",
    "id",
    "uname",
    "date",
    "tr",
    "sort",
    "tmux",
    "ln",
    "cksum",
    "readlink",
    "env",
    "rmdir",
    "mktemp",
    "grep",
    "cat",
    "sha256sum",
    "shasum",
    "dirname",
    "basename",
    "touch",
):
    binary = shutil.which(name)
    if binary:
        (tools / name).symlink_to(binary)
assert not any((tools / name).exists() for name in ("python", "python3", "uv", "go", "node", "npm"))
password = secrets.token_urlsafe(30)
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
(root / "config.yaml").write_text(
    f"web:\n  bind: 127.0.0.1:{port}\n  tls: false\n  password: {json.dumps(password)}\n"
)
(root / "config.yaml").chmod(0o600)
# Service-manager fixtures supervise real Roami processes; no host services are modified.
manager = tools / "systemctl"
manager.write_text(
    "#!"
    + sys.executable
    + "\n"
    + """import json,os,plistlib,signal,subprocess,sys,time
from pathlib import Path
root=Path(os.environ["ROAMI_INSTALL_TEST_ROOT"])
args=[arg for arg in sys.argv[1:] if arg!="--user"]
state=root/"test-service.json"
def stop():
 if state.exists():
  pid=json.loads(state.read_text())["pid"]
  try:
   os.kill(pid,signal.SIGTERM)
   for _ in range(150):
    if (root/"service-stopped").exists(): break
    proc=Path("/proc")/str(pid)/"stat"
    if proc.exists() and proc.read_text().rsplit(")",1)[1].split()[0]=="Z": break
    try: os.kill(pid,0)
    except ProcessLookupError: break
    time.sleep(.1)
  except ProcessLookupError: pass
  state.unlink(missing_ok=True)
def start():
 stop()
 if (root/"fail-next-start").exists():
  (root/"fail-next-start").unlink()
  child=subprocess.Popen(["/bin/sh","-c","exit 44"])
  state.write_text(json.dumps({"pid":child.pid}))
  return
 with (root/"service.log").open("a") as log:
  child=subprocess.Popen([str(root/"bin/roami"),"server"],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 state.write_text(json.dumps({"pid":child.pid}))
if Path(sys.argv[0]).name=="launchctl":
 if args[0]=="unload": stop()
 elif args[0]=="load":
  unit=plistlib.loads(Path(args[1]).read_bytes())
  assert unit["ProgramArguments"]==[str(root/"bin/roami")]
  assert unit["KeepAlive"] is True
  assert unit["EnvironmentVariables"]["ROAMI_HOME"]==str(root)
  start()
 else: sys.exit(1)
elif args[:2]==["is-active","--quiet"]:
 if not state.exists(): sys.exit(1)
 try: os.kill(json.loads(state.read_text())["pid"],0)
 except ProcessLookupError: sys.exit(1)
elif args and args[0]=="restart": start()
elif args and args[0] in ("daemon-reload","enable"): pass
else: sys.exit(1)
"""
)
manager.chmod(0o755)
(tools / "launchctl").symlink_to(manager)


class Downloads(http.server.BaseHTTPRequestHandler):
    broken = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/install.sh":
            file = REPO / "install.sh"
        elif self.path.endswith(".tar.gz.sha256"):
            if self.broken:
                data = ("0" * 64 + "  " + archive.name + "\n").encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)
                return
            file = Path(str(archive) + ".sha256")
        elif self.path.endswith(".tar.gz"):
            file = archive
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(file.stat().st_size))
        self.end_headers()
        with file.open("rb") as source:
            shutil.copyfileobj(source, self.wfile)


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Downloads)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
env = {
    key: value
    for key, value in os.environ.items()
    if not key.startswith(("ROAMI_", "ROAM_", "TTMUX_"))
}
env.update(
    HOME=str(root / "user-home"),
    ROAMI_INSTALL_TEST_ROOT=str(root),
    ROAMI_BIN_DIR=str(root / "bin"),
    ROAMI_INSTALL_ROOT=str(root / "versions with spaces"),
    ROAMI_VERSION=os.environ.get("ROAMI_TEST_VERSION", "dev"),
    ROAMI_RELEASE_BASE_URL=f"http://127.0.0.1:{httpd.server_port}/releases",
    ROAMI_INSTALL_WAIT_SECONDS="15",
    ROAMI_NO_CHROME="1",
    ROAMI_NO_ADB="1",
    ROAMI_NO_KVM="1",
)


def install(name, success=True):
    command = f"curl -fsSL http://127.0.0.1:{httpd.server_port}/install.sh | bash"
    result = subprocess.run(
        [*launcher, "env", "PATH=" + str(tools), "bash", "-o", "pipefail", "-c", command],
        check=False,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
    )
    (root / (name + ".log")).write_text(result.stdout)
    assert (result.returncode == 0) == success, result.stdout[-5000:]


def cli(*args):
    return subprocess.run(
        [*launcher, str(root / "bin/roami"), *args],
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=35,
    )


def wait_status(previous=None):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = cli("agent", "status")
        if response.returncode == 0:
            status = json.loads(response.stdout)["data"]
            if previous is None or status["pid"] != previous:
                return status
        time.sleep(0.1)
    raise AssertionError("runtime not ready: " + (root / "service.log").read_text()[-4000:])


try:
    install("fresh")
    first = wait_status()
    assert first["managed"]
    browser = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    base = f"http://127.0.0.1:{port}"

    def request(path, body=None, method=None):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with browser.open(req, timeout=10) as response:
            return json.load(response)

    request("/api/login", {"password": password})
    settings = request("/api/agent/model-settings")["data"]
    assert settings["main"]["model"] == "" and not settings["connection"]["keyConfigured"]
    conversation = request("/api/agent/conversations", {"title": "Persist across install"})["data"]
    saved_config = (root / "config.yaml").read_bytes()
    current = (root / "versions with spaces/current").readlink()
    install("repeat")
    second = wait_status(first["pid"])
    assert (root / "config.yaml").read_bytes() == saved_config
    request("/api/login", {"password": password})
    catalog = request("/api/agent/conversations")["data"]
    assert conversation["id"] in json.dumps(catalog)
    # A changed archive exercises a new immutable slot with the same protocol/schema.
    upgraded_archive = root / archive.name
    with tarfile.open(archive, "r:gz") as source, tarfile.open(upgraded_archive, "w:gz") as output:
        for member in source:
            if member.isfile():
                payload = source.extractfile(member).read()
                if member.name == "manifest.json":
                    manifest = json.loads(payload)
                    manifest["installationRegression"] = "next-release"
                    payload = json.dumps(manifest).encode()
                    member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))
            else:
                output.addfile(member)
    Path(str(upgraded_archive) + ".sha256").write_text(
        hashlib.sha256(upgraded_archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
    )
    original_archive = archive
    archive = upgraded_archive
    install("upgrade")
    second = wait_status(second["pid"])
    upgraded_slot = (root / "versions with spaces/current").readlink()
    assert upgraded_slot != current
    assert (root / "versions with spaces/previous").readlink() == current
    current = upgraded_slot
    request("/api/login", {"password": password})
    assert conversation["id"] in json.dumps(request("/api/agent/conversations")["data"])
    # Reinstall the original payload, fail startup once and require a working rollback.
    archive = original_archive
    (root / "fail-next-start").touch()
    install("startup-rollback", success=False)
    second = wait_status(second["pid"])
    assert (root / "versions with spaces/current").readlink() == current
    assert (root / "config.yaml").read_bytes() == saved_config
    os.kill(second["pid"], signal.SIGKILL)
    restarted = wait_status(second["pid"])
    assert restarted["managed"]
    Downloads.broken = True
    install("bad-checksum", success=False)
    assert (root / "versions with spaces/current").readlink() == current
    assert wait_status()["pid"] == restarted["pid"]
    assert (root / "config.yaml").read_bytes() == saved_config
    print(
        "PASS: curl | bash, no Python/uv/Go/Node on PATH, settings load, repeated install, preserved data, version activation, startup rollback, child crash recovery, checksum failure preserves running version"
    )
    print("Evidence:", root)
finally:
    httpd.shutdown()
    state = root / "test-service.json"
    if state.exists():
        pid = json.loads(state.read_text())["pid"]
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    subprocess.run([*launcher, "--stop"], env=env, check=True, capture_output=True)
