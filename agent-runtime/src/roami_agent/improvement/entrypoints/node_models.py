"""Saved node routes use the Go CLI's local transport binding without caller overrides."""

import json
from dataclasses import replace

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import load_runtime_model_settings
from roami_agent.tools.process import execute


async def node_model_settings(config, data_root):
    settings = Settings.load(config)
    try:
        result = await execute(
            [settings.cli_bin, "agent", "gateway", "binding", "--data-root", str(data_root)],
            timeout=15,
            max_bytes=16000,
            excluded_env=settings.provider_key_environments(),
        )
        require(result["exitCode"] == 0, "RSI_SHARED_MODEL_GATEWAY_REQUIRED")
        binding = json.loads(result["stdout"])["data"]
        socket = binding["socket"]
        require(
            isinstance(socket, str) and socket.startswith("/"), "RSI_SHARED_MODEL_GATEWAY_REQUIRED"
        )
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        raise DomainError("RSI_SHARED_MODEL_GATEWAY_REQUIRED", 503) from exc
    return await load_runtime_model_settings(
        replace(settings, model_gateway_socket=socket), data_root
    )
