"""Native-service isolation, broker restrictions and unknown-write fencing."""

import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from roami_agent.improvement.evaluation.execution.company_environment import CompanyEnvironment
from roami_agent.improvement.evaluation.execution.company_runtime import (
    CompanyRuntime,
    native_request,
)
from roami_agent.protocol.errors import DomainError


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "http://127.0.0.1:9000/api/v1/users.list", None),
        ("GET", "//other/api/v1/users.list", None),
        ("GET", "/api/v1/users.list#fragment", None),
        ("GET", "/api/v1/users.list?count=101", None),
        ("GET", "/api/v1/users.list?count=1&count=2", None),
        ("GET", "/api/v1/users.list?query=%7B%22%24where%22%3A%22evil%22%7D", None),
        (
            "GET",
            "/api/v1/users.list?query=%7B%22name%22%3A%7B%22%24regex%22%3A%22.*%22%7D%7D",
            None,
        ),
        ("POST", "/api/v1/users.create", {"username": "new"}),
        ("POST", "/api/v1/login", {"user": "other", "password": "unknown"}),
        ("POST", "/api/v1/im.create", {"username": "HR", "extra": True}),
        (
            "POST",
            "/api/v1/chat.postMessage",
            {"roomId": "room", "text": "fetch https://external.example/"},
        ),
    ],
)
def test_broker_rejects_external_administration_and_unbounded_queries(method, path, body):
    with pytest.raises((DomainError, ValueError)):
        native_request(method, path, body)


def test_native_profile_projection_never_accepts_secret_fields():
    path, body = native_request(
        "GET", "/api/v1/users.info?username=HR&fields=%7B%22services%22%3A1%7D", None
    )
    projection = json.loads(parse_qs(urlsplit(path).query)["fields"][0])
    assert "services" not in projection and projection["bio"] == 1
    assert body is None


class Environment:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def request(self, method, path, body):
        self.calls.append((method, path, body))
        if self.fail and method == "POST":
            raise OSError("The server may have applied this write")
        return {"status": 200, "body": {"success": True}}


async def test_successful_duplicate_write_reuses_receipt_without_resending(tmp_path):
    env = Environment()
    runtime = CompanyRuntime(tmp_path / "company.sock", env, time.monotonic() + 10)
    arguments = ("POST", "/api/v1/chat.postMessage", {"roomId": "room", "text": "Done"})
    assert (await runtime.execute(*arguments))["status"] == 200
    assert (await runtime.execute(*arguments))["cached"] is True
    assert len(env.calls) == 1 and len(runtime.records) == 2
    assert all(r["state"] == "succeeded" and r["elapsed_ms"] >= 0 for r in runtime.records)


async def test_unknown_write_blocks_all_later_writes_but_allows_reconciliation(tmp_path):
    env = Environment(fail=True)
    runtime = CompanyRuntime(tmp_path / "company.sock", env, time.monotonic() + 10)
    with pytest.raises(OSError):
        await runtime.execute("POST", "/api/v1/im.create", {"username": "HR"})
    assert runtime.records[0]["state"] == "unknown"
    with pytest.raises(DomainError, match="WRITE_UNKNOWN"):
        await runtime.execute(
            "POST", "/api/v1/chat.postMessage", {"roomId": "room", "text": "Done"}
        )
    await runtime.execute("GET", "/api/v1/im.list")
    assert len(env.calls) == 2


async def test_unix_client_uses_only_case_service_without_receiving_authentication(tmp_path):
    env = Environment()
    runtime = CompanyRuntime(tmp_path / "company.sock", env, time.monotonic() + 10)
    async with runtime:
        reader, writer = await asyncio.open_unix_connection(runtime.socket)
        writer.write(json.dumps({"method": "GET", "path": "/api/v1/users.list"}).encode() + b"\n")
        await writer.drain()
        result = json.loads(await reader.read())
        writer.close()
        await writer.wait_closed()
    assert result == {"status": 200, "body": {"success": True}}
    assert len(runtime.records) == 1 and len(env.calls) == 1
    assert "Auth-Token" not in runtime.records[0]["arguments_json"]


async def test_native_services_have_private_network_memory_limits_and_identity_checked_cleanup(
    monkeypatch,
):
    from roami_agent.improvement.evaluation.execution import company_environment, containers

    digest = hashlib.sha256(b"snapshot").hexdigest()
    env = CompanyEnvironment(
        {"images": {}, "db_dump": base64.b64encode(b"snapshot").decode(), "db_sha256": digest},
        time.monotonic() + 30,
    )
    commands, removed = [], []

    async def images(_):
        return {"mongo": "sha256:" + "a" * 64, "rocketchat": "sha256:" + "b" * 64}

    async def command(*args, **kwargs):
        commands.append((args, kwargs))
        if args[:2] == ("network", "inspect"):
            return json.dumps([{"Labels": {"roami.rsi": env.scope}}]).encode()
        if args[0] == "inspect":
            return json.dumps(
                [{"NetworkSettings": {"Networks": {env.network: {"IPAddress": "172.28.0.2"}}}}]
            ).encode()
        return b"true"

    async def request(method, path, body=None, **kwargs):
        if path == "/api/v1/login":
            return {
                "status": 200,
                "body": {
                    "status": "success",
                    "data": {"userId": "benchmark", "authToken": "ephemeral-fixture-only"},
                },
            }
        if path.startswith("/api/v1/users.list"):
            return {"status": 200, "body": {"users": [], "total": 0}}
        return {"status": 200, "body": {"ims": []}}

    async def remove(name, label):
        assert label == env.scope
        removed.append(name)

    monkeypatch.setattr(company_environment, "resolve_images", images)
    monkeypatch.setattr(env, "command", command)
    monkeypatch.setattr(env, "request", request)
    monkeypatch.setattr(containers, "docker_command", command)
    monkeypatch.setattr(containers, "remove_container", remove)
    await env.start()
    try:
        assert env.initial["actor_id"] == "benchmark"
        create = [args for args, _ in commands if args[0] == "create"]
        assert len(create) == 2
        for args in create:
            assert "--read-only" in args and "--cap-drop" in args and "--memory" in args
            assert "--publish" not in args and "-p" not in args and "host" not in args
            assert "/var/run/docker.sock" not in " ".join(args)
        assert commands[0][0][:3] == ("network", "create", "--internal")
        restore = next(kwargs for args, kwargs in commands if "mongorestore" in args)
        assert restore["input"] == b"snapshot"
    finally:
        await env.close()
    assert removed == [env.scope + "-rocket", env.scope + "-mongo"]
    assert any(args[:2] == ("network", "rm") for args, _ in commands)


@pytest.mark.parametrize(
    "fault", [None, "old_message_only", "wrong_sender", "wrong_recipient", "changed_directory"]
)
async def test_native_checkpoint_success_does_not_prove_fresh_delivery_or_artifact_quality(
    tmp_path, fault
):
    import sys

    from roami_agent.improvement.evaluation.benchmarks.company_tasks import grade_company

    work = tmp_path / "work"
    work.mkdir()
    (work / "leadership_intro.pptx").write_bytes(b"fixture artifact bound by hash")
    old = {"_id": "old", "u": {"_id": "actor"}, "msg": "Completed earlier"}
    new = {
        "_id": "current",
        "u": {"_id": "actor"},
        "msg": "Completed the requested leadership presentation.",
    }
    users = [{"_id": "hr", "name": "Chen Xinyi"}, {"_id": "other", "name": "Other"}]
    initial = {
        "actor_id": "actor",
        "users": users,
        "rooms": [{"_id": "hr-room", "uids": ["hr", "actor"]}],
        "messages": {"hr-room": [old]},
    }
    final = json.loads(json.dumps(initial))
    final["messages"]["hr-room"].append(new)
    if fault == "old_message_only":
        final["messages"]["hr-room"] = [old]
    if fault == "wrong_sender":
        new["u"]["_id"] = "hr"
    if fault == "wrong_recipient":
        final["rooms"][0]["uids"] = ["other", "actor"]
    if fault == "changed_directory":
        final["users"][0]["bio"] = "Changed source profile"
    state = tmp_path / "company-snapshot.json"
    state.write_text(json.dumps({"initial": initial, "final": final}))
    metric = """from common import create_rocketchat_client,get_rocketchat_personal_chat_history
class Result:
 def to_dict(self):return {'checkpoints':[], 'final_score':{'total':5,'result':5}}
def grade_checkpoints():return Result()
"""
    case = {"judge": {"verifier": metric, "scoring": "", "common_helpers": ""}}

    class Local:
        async def sandbox(self, workspace, program, *, input, timeout):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                program,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, error = await asyncio.wait_for(process.communicate(input), timeout)
            assert process.returncode == 0, error.decode()
            return out

    grade = await grade_company(case, work, Local(), state_path=state)
    assert grade["native_metric"] == 1
    assert grade["hard_passed"] is (fault is None)
    assert grade["passed"] is False and grade["quality"] == 0
    assert grade["pending"] is (fault is None)


def test_company_import_keeps_database_answers_and_verifier_outside_agent_view(tmp_path):
    from roami_agent.improvement.evaluation.benchmarks.company_tasks import TASK_ID, import_company
    from roami_agent.improvement.evaluation.contracts import agent_view

    task = tmp_path / "workspaces/tasks" / TASK_ID
    task.mkdir(parents=True)
    (task / "task.md").write_text(
        "Discover leadership profiles in the directory, prepare slides and notify HR."
    )
    (task / "evaluator.py").write_text("# protected native checkpoint fixture\n")
    (tmp_path / "common.py").write_text(
        "def grader(f):\n return f\ndef get_all_texts_from_slide(slide):\n return ''\n"
    )
    (tmp_path / "scoring.py").write_text("# protected scoring fixture\n")
    snapshot = tmp_path / "db.dump"
    snapshot.write_bytes(b"host-only-database-fixture")
    suite = import_company(
        tmp_path,
        snapshot,
        images={
            "mongo": "mongo@sha256:" + "a" * 64,
            "rocketchat": "rocketchat/rocket.chat@sha256:" + "b" * 64,
        },
        revision="c" * 40,
        snapshot_revision="release-fixture",
    )
    case = suite["cases"][0]
    view = json.dumps(agent_view(case, tmp_path))
    assert case["judge"]["rubric_required"] is True
    assert "protected native checkpoint fixture" not in view
    assert case["judge"]["db_dump"] not in view
    assert case["files"] == {} and not case.get("asset_files")
    assert suite["official_leaderboard_comparable"] is False


async def test_service_cleanup_rejects_a_network_whose_identity_changed(monkeypatch):
    from roami_agent.improvement.evaluation.execution import containers

    env = CompanyEnvironment({}, time.monotonic() + 10)
    env.network_created = True
    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        return json.dumps([{"Labels": {"roami.rsi": "another-owner"}}]).encode()

    monkeypatch.setattr(containers, "docker_command", command)
    with pytest.raises(DomainError, match="IDENTITY_CHANGED"):
        await env.close()
    assert commands == [("network", "inspect", env.network)]


async def test_server_error_after_a_post_is_an_unknown_write_not_a_safe_retry(tmp_path):
    class ServerError(Environment):
        async def request(self, *args):
            self.calls.append(args)
            return {"status": 500, "body": {"error": "failure after possible commit"}}

    env = ServerError()
    runtime = CompanyRuntime(tmp_path / "company.sock", env, time.monotonic() + 10)
    result = await runtime.execute("POST", "/api/v1/im.create", {"username": "HR"})
    assert result["status"] == 500 and runtime.records[0]["state"] == "unknown"
    with pytest.raises(DomainError, match="WRITE_UNKNOWN"):
        await runtime.execute("POST", "/api/v1/im.create", {"username": "HR"})
    assert len(env.calls) == 1


async def test_profile_response_strips_credentials_even_if_native_service_ignores_projection(
    tmp_path,
):
    class BroadResponse(Environment):
        async def request(self, *args):
            return {
                "status": 200,
                "body": {
                    "user": {
                        "_id": "hr",
                        "bio": "A source biography",
                        "services": {"password": "not-an-agent-input"},
                    }
                },
            }

    runtime = CompanyRuntime(tmp_path / "company.sock", BroadResponse(), time.monotonic() + 10)
    result = await runtime.execute("GET", "/api/v1/users.info?username=HR")
    assert result["body"]["user"] == {"_id": "hr", "bio": "A source biography"}
    assert "not-an-agent-input" not in json.dumps(runtime.records)


async def test_cleanup_removes_anonymous_database_volumes_after_identity_check(monkeypatch):
    from roami_agent.improvement.evaluation.execution import containers

    commands = []

    async def command(*args, **kwargs):
        commands.append(args)
        return json.dumps([{"Config": {"Labels": {"roami.rsi": "owned"}}}]).encode()

    monkeypatch.setattr(containers, "docker_command", command)
    await containers.remove_container("owned-mongo", "owned")
    assert commands == [("inspect", "owned-mongo"), ("rm", "--force", "--volumes", "owned-mongo")]
    commands.clear()
    with pytest.raises(DomainError, match="IDENTITY_CHANGED"):
        await containers.remove_container("owned-mongo", "other")
    assert len(commands) == 1
