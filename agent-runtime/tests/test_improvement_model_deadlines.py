"""Evaluation requests honor configured limits without inventing a shorter default."""

from dataclasses import replace

import pytest

from roami_agent.improvement.executors import NativeFilesExecutor
from roami_agent.improvement.protocol_suite import protocol_suite
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize(
    "seconds,main_timeout,worker_timeout,expected_main,expected_worker",
    [
        (900, 0, 0, 900, 900),
        (900, 30, 45, 30, 45),
        (900, 1200, 1200, 900, 900),
        (30, 0, 0, 30, 30),
        (900, 30, 0, 30, 900),
    ],
)
async def test_executor_keeps_explicit_deadlines_and_case_upper_bound(
    tmp_path, seconds, main_timeout, worker_timeout, expected_main, expected_worker
):
    observed = {}

    class Rejected:
        model = "deadline-fixture"

        async def stream(self, messages, tools):
            raise DomainError("MODEL_HTTP_401")
            yield ModelEvent("text", "unreachable")

    def factory(settings, role):
        route = settings.route("main" if role == "main" else "worker")
        observed[role] = route.timeout_seconds
        return Rejected()

    settings = Settings(
        timeout_seconds=main_timeout,
        worker_route=replace(Settings().route("worker"), timeout_seconds=worker_timeout),
    )
    case = protocol_suite()["cases"][0]
    case["limits"]["seconds"] = seconds
    result = await NativeFilesExecutor(settings, provider_factory=factory).run(case, {}, tmp_path)
    assert observed == {"main": expected_main, "worker": expected_worker, "memory": expected_worker}
    assert not result["verified_delivery"]


def test_request_deadline_is_bound_to_the_execution_contract():
    unlimited = NativeFilesExecutor(Settings())
    bounded = NativeFilesExecutor(Settings(timeout_seconds=30))
    assert unlimited.model_hash != bounded.model_hash
