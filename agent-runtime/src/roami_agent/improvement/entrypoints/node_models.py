"""Saved node routes and the existing Go daily-quota gateway for CLI inference."""

import os

from roami_agent.improvement.domain.contracts import require
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import load_runtime_model_settings


async def node_model_settings(config, data_root):
    require(os.environ.get("ROAMI_MODEL_GATEWAY_SOCKET"), "RSI_SHARED_MODEL_GATEWAY_REQUIRED")
    return await load_runtime_model_settings(Settings.load(config), data_root)
