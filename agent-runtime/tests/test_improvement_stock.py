"""Native delivery and independent quality are separate requirements."""

import base64
import hashlib
import json
import time

import pytest

from roami_agent.improvement.stock_environment import FOLDER, OUTPUTS, SOURCE, StockEnvironment
from roami_agent.improvement.stock_runtime import StockRuntime
from roami_agent.improvement.stock_tasks import grade_stock
from roami_agent.protocol.errors import DomainError


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("DELETE", FOLDER, None),
        ("GET", "/config/config.php", None),
        ("GET", SOURCE + "?redirect=elsewhere", None),
        ("GET", "http://external/" + SOURCE, None),
        ("MKCOL", "/Documents/Financials", None),
        ("PUT", SOURCE, {"file": "candidate.csv"}),
        ("PUT", FOLDER + "/other.pptx", {"file": "candidate.csv"}),
        ("PUT", FOLDER + "/" + OUTPUTS[0], {"file": "../outside.csv"}),
    ],
)
def test_only_source_reads_and_three_named_deliveries_are_accessible(tmp_path, method, path, body):
    (tmp_path / "candidate.csv").write_text("data")
    env = StockEnvironment({}, time.monotonic() + 10, tmp_path, tmp_path)
    runtime = StockRuntime(tmp_path / "socket", env, time.monotonic() + 10)
    with pytest.raises(DomainError):
        runtime.normalize(method, path, body)


async def test_upload_receipts_bind_content_and_unknown_put_still_allows_get(tmp_path):
    class Environment:
        workspace = tmp_path
        fail = False

        def __init__(self):
            self.calls = []

        async def request(self, method, path, body):
            self.calls.append((method, path, body))
            if self.fail and method == "PUT":
                raise OSError("Ambiguous delivery")
            return {"status": 201 if method == "PUT" else 200, "body": {}}

    file = tmp_path / "data.csv"
    file.write_text("first")
    env = Environment()
    runtime = StockRuntime(tmp_path / "socket", env, time.monotonic() + 10)
    args = ("PUT", FOLDER + "/" + OUTPUTS[0], {"file": "data.csv"})
    await runtime.execute(*args)
    assert (await runtime.execute(*args))["cached"]
    file.write_text("changed")
    await runtime.execute(*args)
    assert len(env.calls) == 2 and env.calls[0][2]["sha256"] != env.calls[1][2]["sha256"]
    file.write_text("unknown")
    env.fail = True
    with pytest.raises(OSError):
        await runtime.execute(*args)
    with pytest.raises(DomainError, match="WRITE_UNKNOWN"):
        await runtime.execute("MKCOL", FOLDER)
    await runtime.execute("GET", FOLDER + "/" + OUTPUTS[0])
    assert runtime.records[-2]["state"] == "unknown" and runtime.records[-1]["state"] == "succeeded"


async def test_post_exit_snapshot_checks_remote_data_hashes(tmp_path):
    env = StockEnvironment({}, time.monotonic() + 10, tmp_path, tmp_path)
    env.initial = {"source_sha256": "source", "outputs": {}}

    async def request(method, path, body=None, **kwargs):
        if path == SOURCE:
            return {"status": 200, "body": {"sha256": "source"}}
        raw = ("native-" + path).encode()
        return {"status": 200, "body": {"content_base64": base64.b64encode(raw).decode()}}

    env.request = request
    state = await env.snapshot(persist=True)
    assert set(state["outputs"]) == set(OUTPUTS)
    for name in OUTPUTS:
        data = (tmp_path / "stock-remote" / name).read_bytes()
        assert state["outputs"][name]["sha256"] == hashlib.sha256(data).hexdigest()
    assert json.loads((tmp_path / "stock-snapshot.json").read_text())["initial"] == env.initial


@pytest.mark.parametrize(
    "fault", [None, "wrong_csv", "local_only", "changed_source", "changed_remote"]
)
async def test_native_csv_pass_still_requires_independent_quality(tmp_path, fault):
    remote = tmp_path / "stock-remote"
    remote.mkdir()
    outputs = {}
    for name in OUTPUTS:
        data = ("native-" + name).encode()
        (remote / name).write_bytes(data)
        outputs[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    state = {
        "initial": {"source_sha256": "source", "outputs": {}},
        "final": {"source_sha256": "source", "outputs": outputs},
    }
    if fault == "local_only":
        state["final"]["outputs"] = {}
    if fault == "changed_source":
        state["final"]["source_sha256"] = "changed"
    if fault == "changed_remote":
        (remote / OUTPUTS[1]).write_text("replaced")
    (tmp_path / "stock-snapshot.json").write_text(json.dumps(state))

    class Executor:
        async def sandbox(self, workspace, program, **kwargs):
            assert workspace == remote
            return json.dumps(
                {
                    "checks": {
                        "adapted_csv_values": fault != "wrong_csv",
                        "five_slides_with_images": True,
                        "nonempty_utf8_script": True,
                    },
                    "native_csv_equality": fault != "wrong_csv",
                }
            ).encode()

    grade = await grade_stock({"judge": {"raw_sha256": "source"}}, Executor(), root=tmp_path)
    assert grade["hard_passed"] is (fault is None) and grade["pending"] is (fault is None)
    assert not grade["passed"] and grade["quality"] == 0
    assert grade["native_partial"]["unscored_points"] == (
        8 if fault in {"local_only", "changed_remote"} else 7
    )


async def test_cleanup_removes_only_identity_checked_owned_data_volume(monkeypatch, tmp_path):
    from roami_agent.improvement import containers

    env = StockEnvironment({}, time.monotonic() + 10, tmp_path, tmp_path)
    name = env.scope + "-owncloud"
    env.containers = [name]
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        return json.dumps(
            [
                {
                    "Config": {"Labels": {"roami.rsi": env.scope}},
                    "Mounts": [{"Type": "volume", "Destination": "/var/www/html"}],
                }
            ]
        ).encode()

    monkeypatch.setattr(containers, "docker_command", command)
    await env.close()
    assert ("rm", "--force", "--volumes", name) in commands
