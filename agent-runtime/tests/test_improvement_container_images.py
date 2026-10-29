"""Container image capability follows the effective route without copying credentials."""

import json
from dataclasses import replace

import pytest

from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.execution.container_agent import container_settings
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


async def test_effective_worker_image_input_reaches_container_request(tmp_path, monkeypatch):
    settings = Settings()
    route = replace(
        settings.route("worker"),
        endpoint="http://private.invalid/v1",
        key_env="PRIVATE_PROVIDER_KEY",
        capabilities={"images": True, "private": "do not transfer"},
        image_limits={"max_width": 900},
    )

    async def docker(*args, **kwargs):
        if args[0] == "start":
            raise TimeoutError
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(settings, worker_route=route)
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    await executor.run(protocol_suite()["cases"][0], {}, tmp_path)
    request = json.loads((tmp_path / "state" / "request.json").read_text())
    assert request["worker_image_input"] == {"enabled": True, "limits": {"max_width": 900}}
    assert "private.invalid" not in json.dumps(request)
    assert "PRIVATE_PROVIDER_KEY" not in json.dumps(request)
    child = container_settings(request)
    assert child.route("worker").capabilities == {"images": True}
    assert child.route("worker").image_limits == {"max_width": 900}
    assert child.route("worker").endpoint == "http://localhost/v1/main"
    assert child.route("main").capabilities.get("images") is not True
    other = containers.ContainerExecutor(
        settings, worker_route=replace(route, image_limits={"max_width": 901})
    )
    assert other.model_hash != executor.model_hash


@pytest.mark.parametrize("enabled", [False, True])
def test_container_uses_only_explicit_image_capability(enabled):
    settings = container_settings({"worker_image_input": {"enabled": enabled, "limits": {}}})
    assert settings.route("worker").capabilities == {"images": enabled}
    assert container_settings({}).route("worker").capabilities.get("images") is not True


@pytest.mark.parametrize(
    "image_input",
    [
        {},
        {"enabled": 1, "limits": {}},
        {"enabled": True, "limits": {}, "endpoint": "x"},
        {"enabled": True, "limits": {"max_width": 0}},
    ],
)
def test_invalid_container_image_input_is_rejected(image_input):
    with pytest.raises(DomainError):
        container_settings({"worker_image_input": image_input})


@pytest.mark.parametrize("labels", [None, {}, {"org.roami.rsi.workspace-image-input": "1"}])
async def test_visual_worker_requires_a_capable_container_image(labels, monkeypatch):
    async def docker(*args, **kwargs):
        return json.dumps([{"Id": "fixture-image", "Config": {"Labels": labels}}]).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    settings = Settings()
    executor = containers.ContainerExecutor(
        settings, worker_route=replace(settings.route("worker"), capabilities={"images": True})
    )
    if labels:
        assert (await executor.preflight())["image_id"] == "fixture-image"
    else:
        with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
            await executor.preflight()
