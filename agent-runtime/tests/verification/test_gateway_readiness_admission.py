"""Trusted local readiness and key rejections happen before the upstream call."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume

from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[3] / "cases/case-102-mech-gp02/input/controls.json"
    ).read_text()
)


@pytest.mark.parametrize(
    "status,code",
    [(row["status"], row["code"]) for row in CONTROLS["rejections"]],
)
async def test_local_readiness_or_key_rejection_is_known_zero_and_not_retried(
    tmp_path, status, code
):
    socket, seen = str(tmp_path / "gateway.sock"), []

    async def no_retry(delay):
        pytest.fail("A trusted Go admission rejection must not enter HTTP retry policy")

    provider = configured_provider(
        Settings(
            endpoint="https://must-not-connect.invalid/v1",
            model="fixture",
            model_gateway_socket=socket,
            model_retries=3,
        ),
        "main",
    )
    provider.sleep = no_retry
    budget, journal = EpisodeBudget({"seconds": 30}, shared_daily_limit=True), []
    model = MeteredModel(provider, budget, "main", journal=journal)
    try:
        async with gateway_fixture(socket, seen, status=status, code=code):
            with pytest.raises(ModelAdmissionRejected) as error:
                await consume(model)
            assert error.value.code == code
    finally:
        await provider.close()
    assert len(seen) == 1
    assert budget.metrics()["request_attempts"] == budget.metrics()["observed_tokens"] == 0
    assert budget.metrics()["token_coverage"] == "complete"
    assert journal[0]["admission_rejected"] and journal[0]["error_code"] == code


@pytest.mark.parametrize(
    "status,code",
    [(row["status"], row["code"]) for row in CONTROLS["rejections"]],
)
async def test_remote_header_does_not_claim_trusted_zero_usage(status, code):
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(status, headers={"X-Roami-Model-Error": code}, content=b"{}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    provider = configured_provider(
        Settings(endpoint="https://fixture-provider.invalid/v1", model="fixture", model_retries=0),
        "main",
        client=client,
    )
    budget, journal = EpisodeBudget({"seconds": 30}, shared_daily_limit=True), []
    model = MeteredModel(provider, budget, "main", journal=journal)
    try:
        with pytest.raises(DomainError) as error:
            await consume(model)
    finally:
        await provider.close()
    assert not isinstance(error.value, ModelAdmissionRejected)
    assert error.value.code == "MODEL_HTTP_" + str(status)
    assert len(seen) == 1 and "admission_rejected" not in journal[0]
    assert budget.metrics()["token_coverage"] != "complete"


async def test_rejection_after_earlier_attempt_does_not_erase_unknown_usage(tmp_path):
    socket, seen = str(tmp_path / "gateway.sock"), []
    provider = configured_provider(
        Settings(
            endpoint="https://must-not-connect.invalid/v1",
            model="fixture",
            model_gateway_socket=socket,
            model_retries=1,
        ),
        "main",
    )
    provider.sleep = lambda delay: asyncio.sleep(0)
    budget, journal = EpisodeBudget({"seconds": 30}, shared_daily_limit=True), []
    model = MeteredModel(provider, budget, "main", journal=journal)
    try:
        async with gateway_fixture(
            socket,
            seen,
            status=503,
            code=lambda count: None if count == 1 else "MODEL_GATEWAY_UNAVAILABLE",
        ):
            with pytest.raises(DomainError) as error:
                await consume(model)
    finally:
        await provider.close()
    assert not isinstance(error.value, ModelAdmissionRejected)
    assert error.value.code == "MODEL_GATEWAY_UNAVAILABLE" and len(seen) == 2
    assert "admission_rejected" not in journal[0]
    assert budget.metrics()["token_coverage"] != "complete"
