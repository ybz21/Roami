"""Standalone RSI binds the selected local node without environment or model overrides."""

import asyncio
import json

import pytest
from test_improvement_cli_node_models import node
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume

from roami_agent.improvement.entrypoints.node_models import node_model_settings
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.providers.factory import configured_provider


@pytest.mark.parametrize("status,code", [(200, None), (402, "MODEL_PROXY_DAILY_LIMIT")])
async def test_cli_discovers_go_binding_and_preserves_saved_model_parameters(
    tmp_path, monkeypatch, status, code
):
    root, config, saved = node(tmp_path, monkeypatch)
    before = saved.read_bytes()
    socket = str(tmp_path / "model.sock")
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", "/foreign-node/must-not-use.sock")
    commands = []

    async def binding(argv, **options):
        commands.append(argv)
        assert "ROAMI_AGENT_API_KEY" in options["excluded_env"]
        return {"exitCode": 0, "stdout": json.dumps({"data": {"socket": socket}}), "stderr": ""}

    monkeypatch.setattr("roami_agent.improvement.entrypoints.node_models.execute", binding)
    seen = []
    async with gateway_fixture(socket, seen, status=status, code=code):
        settings = await node_model_settings(config, root)
        provider = configured_provider(settings, "worker")
        try:
            if code:
                with pytest.raises(ModelAdmissionRejected, match=code):
                    await consume(provider)
            else:
                assert any(e.kind == "text" and e.value == "hello" for e in await consume(provider))
        finally:
            await provider.close()
    assert len(commands) == len(seen) == 1 and commands[0][-2:] == ["--data-root", str(root)]
    assert seen[0][2]["model"] == "saved-worker"
    assert seen[0][2]["max_tokens"] == 8192 and seen[0][2]["temperature"] == 0.4
    assert "x-roami-model-upstream" not in seen[0][1] and "authorization" not in seen[0][1]
    assert len(seen[0][1]["x-roami-model-route"]) == 64
    assert saved.read_bytes() == before


@pytest.mark.parametrize(
    "response",
    [
        {"exitCode": 1, "stdout": "", "stderr": "private local diagnostic"},
        {"exitCode": 0, "stdout": "invalid JSON", "stderr": ""},
        {"exitCode": 0, "stdout": '{"data":{"socket":"https://external.invalid"}}', "stderr": ""},
    ],
)
async def test_unavailable_local_binding_stops_before_provider_construction(
    tmp_path, monkeypatch, response
):
    root, config, _ = node(tmp_path, monkeypatch)
    monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET")

    async def binding(*args, **options):
        return response

    monkeypatch.setattr("roami_agent.improvement.entrypoints.node_models.execute", binding)
    with pytest.raises(DomainError, match="RSI_SHARED_MODEL_GATEWAY_REQUIRED"):
        await node_model_settings(config, root)


async def test_concurrent_nodes_do_not_share_or_mutate_process_gateway_binding(
    tmp_path, monkeypatch
):
    one, c1, _ = node(tmp_path / "one", monkeypatch)
    two, c2, _ = node(tmp_path / "two", monkeypatch)
    monkeypatch.delenv("ROAMI_MODEL_GATEWAY_SOCKET")
    sockets = {str(one): str(tmp_path / "a.sock"), str(two): str(tmp_path / "b.sock")}

    async def binding(argv, **options):
        await asyncio.sleep(0)
        return {
            "exitCode": 0,
            "stdout": json.dumps({"data": {"socket": sockets[argv[-1]]}}),
            "stderr": "",
        }

    monkeypatch.setattr("roami_agent.improvement.entrypoints.node_models.execute", binding)
    first, second = await asyncio.gather(node_model_settings(c1, one), node_model_settings(c2, two))
    assert first.model_gateway_socket == sockets[str(one)]
    assert second.model_gateway_socket == sockets[str(two)]
    import os

    assert "ROAMI_MODEL_GATEWAY_SOCKET" not in os.environ
