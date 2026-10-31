"""Failed sandbox commands keep private diagnostics without changing verdicts or replaying."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_improvement_control import suite_file

from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.container_failure_evidence import (
    MAX_FAILURES,
    STDERR_BYTES,
    ContainerCommandFailure,
    capture_failures,
    failure_fields,
)
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.improvement.workflows.pipeline_reports import public_issue_body
from roami_agent.improvement.workflows.pipeline_runner import enqueue_diagnostic, execute_diagnostic
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings

FIXTURE = json.loads((Path(__file__).parent / "fixtures/container-failures.json").read_text())


class Process:
    def __init__(self, out=b"", err=b"", code=0):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(out)
        self.stdout.feed_eof()
        self.stderr.feed_data(err)
        self.stderr.feed_eof()
        self.returncode = code

    async def wait(self):
        await asyncio.sleep(0)
        return self.returncode


@pytest.fixture
def docker(monkeypatch):
    processes = []
    calls = []

    async def create(*args, **kwargs):
        calls.append(args)
        return processes.pop(0)

    monkeypatch.setattr(containers.asyncio, "create_subprocess_exec", create)
    return processes, calls


def failed(stderr=None, code=None):
    return Process(
        err=(stderr if stderr is not None else FIXTURE["stderr"]).encode(),
        code=code or FIXTURE["exit_code"],
    )


async def test_success_keeps_stdout_and_ignores_stderr_noise(docker):
    processes, calls = docker
    processes.append(Process(b"known output", b"warning", 0))
    assert await containers.docker_command("start", "example") == b"known output"
    assert len(calls) == 1


async def test_failure_preserves_stderr_exit_and_does_not_retry(docker):
    processes, calls = docker
    processes.append(failed())
    with pytest.raises(ContainerCommandFailure) as raised:
        await containers.docker_command("start", "example")
    error = raised.value
    assert error.code == FIXTURE["expected_public_code"] and str(error) == error.code
    assert error.diagnostic == {
        "operation": "start",
        "exit_code": 23,
        "stderr": FIXTURE["stderr"],
        "stderr_truncated": False,
    }
    assert len(calls) == 1


async def test_command_arguments_and_stdout_are_not_error_evidence(docker):
    processes, calls = docker
    processes.append(Process(b"private-stdout", b"failure", 1))
    with pytest.raises(ContainerCommandFailure) as raised:
        await containers.docker_command("create", "--env", "PRIVATE_INPUT=not-recorded")
    text = json.dumps(failure_fields(raised.value))
    assert "private-stdout" not in text and "PRIVATE_INPUT" not in text
    assert len(calls) == 1 and "failure" in text


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
async def test_existing_stream_bound_still_rejects_oversized_output(docker, channel):
    processes, _ = docker
    processes.append(
        Process(
            out=b"x" * 20 if channel == "stdout" else b"",
            err=b"x" * 20 if channel == "stderr" else b"",
        )
    )
    with pytest.raises(DomainError, match="RSI_DOCKER_OUTPUT_LIMIT"):
        await containers.docker_command("start", "example", maximum=10)


def test_redaction_happens_before_utf8_tail_truncation():
    credential = "sk-synthetic_fixture_credential_1234"
    error = ContainerCommandFailure(
        "start",
        1,
        ("header " + credential + "\n" + "界" * 3000 + "\nBearer synthetic-access-value").encode(),
    )
    text = error.diagnostic["stderr"]
    assert len(text.encode()) <= STDERR_BYTES
    assert credential not in text and "synthetic-access-value" not in text and "[redacted]" in text
    assert error.diagnostic["stderr_truncated"]


def test_unknown_operation_never_copies_arbitrary_argument():
    assert ContainerCommandFailure("private-argument", 1, b"x").diagnostic["operation"] == "command"


async def test_caught_native_failure_survives_to_case_result(docker):
    processes, calls = docker
    processes.append(failed())

    @capture_failures
    async def run():
        try:
            await containers.docker_command("start", "example")
        except DomainError:
            return {"grade": {"passed": False, "reason": "native_check_failed"}}

    result = await run()
    assert result["grade"] == {"passed": False, "reason": "native_check_failed"}
    assert result["execution_diagnostics"]["failures"][0]["stderr"] == FIXTURE["stderr"]
    assert len(calls) == 1


async def test_rewrapped_preflight_failure_retains_first_command_evidence(docker):
    processes, _ = docker
    processes.append(failed())

    @capture_failures
    async def run():
        try:
            await containers.docker_command("image", "inspect", "example")
        except DomainError:
            raise DomainError("RSI_CONTAINER_IMAGE_REQUIRED") from None

    with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED") as raised:
        await run()
    assert (
        failure_fields(raised.value)["execution_diagnostics"]["failures"][0]["operation"] == "image"
    )


async def test_parallel_cases_keep_separate_diagnostics(docker):
    processes, _ = docker
    processes.extend([failed("alpha failure"), failed("beta failure")])

    @capture_failures
    async def run():
        try:
            await containers.docker_command("start", "example")
        except DomainError:
            return {"grade": {"passed": False}}

    a, b = await asyncio.gather(run(), run())
    assert a["execution_diagnostics"]["failures"][0]["stderr"] == "alpha failure"
    assert b["execution_diagnostics"]["failures"][0]["stderr"] == "beta failure"


async def test_record_bound_reports_omitted_failures():
    @capture_failures
    async def run():
        for i in range(MAX_FAILURES + 3):
            ContainerCommandFailure("start", i + 1, b"failure")
        return {"grade": {"passed": False}}

    evidence = (await run())["execution_diagnostics"]
    assert len(evidence["failures"]) == MAX_FAILURES and evidence["omitted_failures"] == 3


async def test_cleanup_does_not_replace_first_failure_evidence(docker):
    processes, _ = docker
    processes.extend([failed("first command failed"), failed("cleanup failed")])

    @capture_failures
    async def run():
        try:
            try:
                await containers.docker_command("start", "example")
            finally:
                await containers.docker_command("rm", "example")
        except DomainError:
            return {"grade": {"passed": False}}

    rows = (await run())["execution_diagnostics"]["failures"]
    assert [(r["operation"], r["stderr"]) for r in rows] == [
        ("start", "first command failed"),
        ("rm", "cleanup failed"),
    ]


async def test_context_resets_after_an_exception():
    @capture_failures
    async def first():
        raise ContainerCommandFailure("start", 1, b"first failure")

    @capture_failures
    async def next_run():
        return {"grade": {"passed": True}}

    with pytest.raises(ContainerCommandFailure):
        await first()
    assert "execution_diagnostics" not in await next_run()


async def test_cancellation_stays_cancellation():
    @capture_failures
    async def run():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run()


async def test_success_cannot_claim_unrecorded_host_failures():
    @capture_failures
    async def run():
        return {"grade": {"passed": True}, "execution_diagnostics": {"failures": ["forged"]}}

    assert "execution_diagnostics" not in await run()


def test_trial_summary_preserves_diagnostic_without_changing_failure_or_usage():
    detail = failure_fields(ContainerCommandFailure("start", 23, FIXTURE["stderr"].encode()))
    result = {
        "grade": {"passed": False, "pending": False, "reason": "RSI_DOCKER_COMMAND_FAILED"},
        "metrics": {"tokens": None, "token_coverage": "unknown"},
        **detail,
    }
    value = trial_summary({"id": "synthetic"}, result)
    assert value["execution_diagnostics"] == detail["execution_diagnostics"] and not value["passed"]
    assert value["metrics"]["tokens"] is None and "RSI_DOCKER_COMMAND_FAILED" in value["signals"]


def test_legacy_results_do_not_gain_fake_diagnostics():
    assert not failure_fields({"grade": {"passed": False}})
    assert "execution_diagnostics" not in trial_summary(
        {"id": "synthetic"}, {"grade": {"passed": False}}
    )


async def test_pipeline_persists_failure_evidence_without_publication_leak(tmp_path, monkeypatch):
    service = ImprovementStatus(tmp_path)
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )

    class Executor(containers.ContainerExecutor):
        async def preflight(self):
            return {"environment_hash": "a" * 64}

        @capture_failures
        async def run(self, case, policy, target):
            raise ContainerCommandFailure("start", 23, b"private diagnostic sentinel")

    monkeypatch.setattr(containers, "ContainerExecutor", Executor)
    run = enqueue_diagnostic(service, "local", {"request_key": "stderr", "case_ids": ["a"]})
    await execute_diagnostic(
        SimpleNamespace(settings=SimpleNamespace(current=Settings())),
        service,
        service.control.claim(),
    )
    value = service.runs.get("local", run["id"])
    case = value["cases"][0]
    assert (
        not case["passed"]
        and case["execution_diagnostics"]["failures"][0]["stderr"] == "private diagnostic sentinel"
    )
    artifact = next(a for a in value["artifacts"] if a["name"] == "results.json")
    assert (
        "private diagnostic sentinel"
        in service.runs.read_artifact("local", run["id"], artifact["id"])["text"]
    )
    assert "private diagnostic sentinel" not in public_issue_body(value, {})
    with pytest.raises(DomainError, match="RSI_RUN_NOT_FOUND"):
        service.runs.get("other", run["id"])


async def test_actual_preflight_wrapper_keeps_command_diagnostic(docker):
    processes, _ = docker
    processes.append(failed("synthetic missing image"))
    with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED") as raised:
        await containers.ContainerExecutor(Settings()).preflight()
    rows = failure_fields(raised.value)["execution_diagnostics"]["failures"]
    assert rows[0]["operation"] == "image" and rows[0]["stderr"] == "synthetic missing image"


async def test_pipeline_preflight_failure_has_private_stage_artifact(tmp_path, docker):
    processes, _ = docker
    processes.append(failed("private image failure sentinel"))
    service = ImprovementStatus(tmp_path)
    service.control.register_machine(
        "local", {"id": "a", "label": "A", "mode": "container"}, local_only=True
    )
    service.control.register_suite("local", suite_file(tmp_path))
    service.control.save(
        "local", {**service.control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]}
    )
    run = enqueue_diagnostic(service, "local", {"request_key": "image-stderr", "case_ids": ["a"]})
    with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
        await execute_diagnostic(
            SimpleNamespace(settings=SimpleNamespace(current=Settings())),
            service,
            service.control.claim(),
        )
    value = service.runs.get("local", run["id"])
    assert value["cases"] == []
    artifact = next(a for a in value["artifacts"] if a["name"] == "environment-failure.json")
    assert (
        "private image failure sentinel"
        in service.runs.read_artifact("local", run["id"], artifact["id"])["text"]
    )
    assert "private image failure sentinel" not in public_issue_body(value, {})
