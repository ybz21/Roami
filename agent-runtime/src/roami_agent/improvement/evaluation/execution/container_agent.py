"""Unprivileged container entry; no grader inputs or provider keys are mounted."""

import asyncio
import json
import os
from pathlib import Path

import httpx

from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.protocol.model_routes import settings_with_route
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings


async def main():
    Path.home().mkdir(parents=True, exist_ok=True)
    request = json.loads(Path("/state/request.json").read_text())
    case = request["case"]
    case.update(
        files={},
        judge={"kind": "rubric"},
        counts_as_delivery=True,
        layer="authored_real",
        split="development",
        category="CONTAINER",
    )
    settings = Settings(
        endpoint="http://localhost/v1/main",
        model="main",
        key_env="RSI_NO_PROVIDER_KEY",
        worker_model="worker",
        model_retries=0,
    )

    # Configure each provider with a separate Unix-socket transport to the host's budget gateway.
    def via_gateway(settings_, role):
        from dataclasses import replace

        actual = "main" if role == "main" else "worker"
        route = settings_.route(actual)
        route = replace(route, endpoint="http://localhost/v1/" + role, name=actual)
        client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds="/model/gateway.sock"),
            timeout=httpx.Timeout(case["limits"]["seconds"], connect=10),
        )
        return configured_provider(
            settings_with_route(settings_, actual, route), actual, client=client
        )

    executor = NativeFilesExecutor(
        settings,
        allow_shell=True,
        allow_tasks=True,
        workspace=Path("/workspace"),
        settle_maintenance=True,
        provider_factory=via_gateway,
        shared_daily_limit=request.get("shared_daily_limit") is True,
    )
    result = await executor.run(case, request["policy"], Path("/state"))
    private_json(Path("/state/response.json"), result)


def run():
    if os.environ.get("ROAMI_RSI_CONTAINER") != "1":
        raise SystemExit("RSI_CONTAINER_REQUIRED")
    asyncio.run(main())


if __name__ == "__main__":
    run()
