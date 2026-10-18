"""Generation settings are explicit per role and part of cache/manifests identity."""

import json

import httpx
import pytest

from roami_agent.app import configured_provider
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.server.configuration import Settings


async def test_main_and_worker_parameters_are_independent_and_reach_the_provider(tmp_path):
    config = tmp_path / "agent.toml"
    config.write_text(
        '[model]\nendpoint="https://main.invalid/v1"\nname="quick"\n[model.parameters]\nreasoning_effort="low"\nmax_tokens=300\n[worker.model]\nname="worker"\n[worker.model.parameters]\nreasoning_effort="high"\n'
    )
    settings = Settings.load(config)
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    main = configured_provider(
        settings, "main", client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    worker = configured_provider(
        settings, "worker", client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    try:
        for provider in (main, worker):
            _ = [
                event
                async for event in provider.stream([{"role": "user", "content": "question"}], [])
            ]
        assert requests[0]["reasoning_effort"] == "low" and requests[0]["max_tokens"] == 300
        assert requests[1]["reasoning_effort"] == "high" and "max_tokens" not in requests[1]
        assert main.settings_hash != worker.settings_hash
    finally:
        await main.close()
        await worker.close()


async def test_parameter_identity_is_stable_and_explicit_worker_does_not_inherit_main_controls(
    tmp_path,
):
    config = tmp_path / "agent.toml"
    config.write_text(
        '[model]\nendpoint="https://provider.invalid/v1"\nname="same"\n[model.parameters]\nreasoning_effort="low"\n[worker.model]\nname="same"\n'
    )
    settings = Settings.load(config)
    main = configured_provider(settings, "main")
    worker = configured_provider(settings, "worker")
    original = {"temperature": 0.2, "reasoning_effort": "low"}
    first = ChatCompletions("https://provider.invalid/v1", "same", parameters=original)
    second = ChatCompletions(
        "https://provider.invalid/v1",
        "same",
        parameters={"reasoning_effort": "low", "temperature": 0.2},
    )
    try:
        assert worker.parameters == {} and main.parameters == {"reasoning_effort": "low"}
        assert (
            main.settings_hash != worker.settings_hash and main.provider_key == worker.provider_key
        )
        assert first.settings_hash == second.settings_hash
        original["temperature"] = 1.5
        assert first.parameters["temperature"] == 0.2
    finally:
        await main.close()
        await worker.close()
        await first.close()
        await second.close()


@pytest.mark.parametrize(
    "parameters",
    [
        {"model": "other"},
        {"messages": []},
        {"tools": []},
        {"stream": False},
        {"api_key": "fixture"},
        {"temperature": True},
        {"temperature": float("nan")},
        {"temperature": 10**500},
        {"temperature": 2.1},
        {"max_tokens": True},
        {"max_tokens": 0},
        {"max_tokens": 1_000_001},
        {"reasoning_effort": "unexpected"},
        {"reasoning_effort": {}},
        {"top_p": 1.1},
    ],
)
def test_invalid_parameters_fail_before_any_provider_request(parameters):
    with pytest.raises(DomainError, match="INVALID_MODEL_PARAMETERS"):
        ChatCompletions("https://provider.invalid/v1", "fixture", parameters=parameters)
