"""Role routing preserves provider boundaries and keeps credentials out of subprocesses."""

import json
import sys
from dataclasses import replace

import httpx
import pytest

from roami_agent.app import configured_provider
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.tools.registry import Tools
from roami_agent.tools.shell import register_shell


def configuration(
    tmp_path,
    worker='name="vision"\nendpoint="https://worker.invalid/v1"\nkey_env="WORKER_PROVIDER_KEY"\ntimeout_seconds=9\n',
):
    path = tmp_path / "routes.toml"
    path.write_text(
        '[model]\nname="fast"\nendpoint="https://main.invalid/v1"\nkey_env="MAIN_PROVIDER_KEY"\n'
        '[model.capabilities]\nversion="main-route-v1"\nimages=false\n'
        "[runtime]\ntimeout_seconds=3\n"
        "[worker.model]\n" + worker
    )
    return Settings.load(path)


async def test_distinct_role_routes_use_their_own_key_model_capabilities_and_cache(
    tmp_path, monkeypatch
):
    settings = configuration(
        tmp_path,
        'name="vision"\nendpoint="https://worker.invalid/v1"\nkey_env="WORKER_PROVIDER_KEY"\ntimeout_seconds=9\n[worker.model.capabilities]\nimages=true\nversion="vision-v1"\n',
    )
    monkeypatch.setenv("MAIN_PROVIDER_KEY", "fixture-main")
    monkeypatch.setenv("WORKER_PROVIDER_KEY", "fixture-worker")
    requests = []

    async def handle(request):
        requests.append(
            (request.url.host, request.headers["authorization"], json.loads(request.content))
        )
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    main = configured_provider(
        settings, "main", client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    worker = configured_provider(
        settings, "worker", client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    image = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}
            ],
        }
    ]
    try:
        assert settings.timeout_for("main") == 3 and settings.timeout_for("worker") == 9
        assert main.provider_key != worker.provider_key
        with pytest.raises(DomainError, match="MODEL_IMAGES_UNSUPPORTED"):
            _ = [part async for part in main.stream(image, [])]
        _ = [
            part async for part in main.stream([{"role": "user", "content": "quick question"}], [])
        ]
        _ = [part async for part in worker.stream(image, [])]
        assert [(host, key, payload["model"]) for host, key, payload in requests] == [
            ("main.invalid", "Bearer fixture-main", "fast"),
            ("worker.invalid", "Bearer fixture-worker", "vision"),
        ]
        assert all("prompt_cache_key" not in payload for _, _, payload in requests)
    finally:
        await main.close()
        await worker.close()


def test_legacy_worker_model_inherits_route_but_explicit_worker_defaults_to_own_capabilities(
    tmp_path,
):
    legacy = Settings(
        endpoint="https://legacy.invalid/v1",
        model="fast",
        worker_model="worker",
        model_capabilities={"images": True},
    )
    assert legacy.route("worker").name == "worker" and legacy.route("worker").capabilities["images"]
    explicit = configuration(tmp_path)
    assert explicit.route("worker").capabilities == {} and explicit.route("worker").cache == {}


@pytest.mark.parametrize(
    "worker",
    [
        "timeout_seconds=-1",
        "timeout_seconds=true",
        "max_retries=4",
        'key_env="BAD-NAME"',
        'endpoint="http://remote.invalid/v1"',
    ],
)
def test_invalid_worker_routes_fail_before_model_use(tmp_path, worker):
    with pytest.raises(DomainError):
        configuration(tmp_path, worker + "\n")


async def test_shell_removes_both_provider_keys_and_preserves_unrelated_environment(
    tmp_path, monkeypatch
):
    settings = configuration(tmp_path)
    settings = replace(settings, shell_roots=(tmp_path,))
    for name in (
        "MAIN_PROVIDER_KEY",
        "WORKER_PROVIDER_KEY",
        "ROAMI_AGENT_API_KEY",
        "GIT_DIR",
        "ROAMI_ROUTE_TEST",
    ):
        monkeypatch.setenv(name, "fixture")
    names = [
        "MAIN_PROVIDER_KEY",
        "WORKER_PROVIDER_KEY",
        "ROAMI_AGENT_API_KEY",
        "GIT_DIR",
        "ROAMI_ROUTE_TEST",
    ]
    script = (
        "import os,json; print(json.dumps({name: name in os.environ for name in "
        + repr(names)
        + "}))"
    )
    tools = Tools()
    register_shell(tools, settings)
    result = await tools.invoke(
        {
            "id": "env",
            "function": {
                "name": "shell",
                "arguments": json.dumps(
                    {"cwd": str(tmp_path), "argv": [sys.executable, "-c", script]}
                ),
            },
        },
        "worker",
        {},
    )
    assert json.loads(result["stdout"]) == {name: name == "ROAMI_ROUTE_TEST" for name in names}


async def test_computer_uses_worker_vision_capability_even_when_main_is_text_only(store, tmp_path):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime

    settings = configuration(
        tmp_path,
        'name="vision"\n[worker.model.capabilities]\nimages=true\n',
    )
    settings = replace(settings, computer={"enabled": True})
    runtime = Runtime(store, ConversationModel(), settings=settings)
    try:
        assert runtime.loop.context.vision is not None
        assert all(
            "computer" not in item["function"]["name"] for item in runtime.tools.catalog("main")
        )
    finally:
        await runtime.close()
