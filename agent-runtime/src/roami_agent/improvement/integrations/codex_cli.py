"""Codex configuration and bounded process execution, without operation-ledger rules."""

import asyncio
import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.protocol.errors import DomainError
from roami_agent.tools.process import execute


def codex_configuration(*, shared_gateway=False):
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = home / "config.toml"
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    # Preserve model routing/authentication, without loading personal hooks, MCPs or plugins.
    selected = {
        k: config[k]
        for k in ("model", "model_provider", "model_reasoning_effort")
        if k in config and not (shared_gateway and k == "model_provider")
    }
    provider = (
        {}
        if shared_gateway
        else config.get("model_providers", {}).get(config.get("model_provider"), {})
    )
    allowed = {
        "name",
        "base_url",
        "wire_api",
        "env_key",
        "requires_openai_auth",
        "env_http_headers",
    }
    require(
        not (
            set(provider)
            - allowed
            - {"request_max_retries", "stream_max_retries", "stream_idle_timeout_ms"}
        ),
        "RSI_CODEX_PROVIDER_CONFIG_UNSUPPORTED",
    )
    if provider.get("base_url"):
        url = urlsplit(provider["base_url"])
        require(
            url.scheme in {"https", "http"}
            and bool(url.hostname)
            and not (url.username or url.password or url.query or url.fragment),
            "RSI_CODEX_PROVIDER_CONFIG_UNSUPPORTED",
        )
    if provider:
        name = config["model_provider"]
        require(
            name.replace("_", "").replace("-", "").isalnum(),
            "RSI_CODEX_PROVIDER_CONFIG_UNSUPPORTED",
        )
        for key in allowed & set(provider):
            value = provider[key]
            if key == "env_http_headers":
                require(
                    isinstance(value, dict)
                    and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()),
                    "RSI_CODEX_PROVIDER_CONFIG_UNSUPPORTED",
                )
                selected[f"model_providers.{name}.env_http_headers"] = value
            else:
                selected[f"model_providers.{name}.{key}"] = value
        for key in ("request_max_retries", "stream_max_retries"):
            selected[f"model_providers.{name}.{key}"] = 0
    variables = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "CODEX_HOME",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
    }
    if provider.get("env_key"):
        variables.add(provider["env_key"])
    variables.update(provider.get("env_http_headers", {}).values())
    return selected, {k: os.environ[k] for k in variables if k in os.environ}


async def run_codex(argv, *, cwd, timeout, max_bytes, **kwargs):
    journal = cwd / "journal"
    journal.mkdir(mode=0o700)
    task = asyncio.create_task(
        execute(argv, cwd=cwd, timeout=timeout, output_directory=journal, **kwargs)
    )
    try:
        while not task.done():
            await asyncio.sleep(0.1)
            require(
                all(p.stat().st_size <= max_bytes for p in journal.iterdir()),
                "PROCESS_OUTPUT_LIMIT",
            )
        result = await task
        return {
            "exitCode": result["exitCode"],
            **{k: result[k].read_text(errors="replace") for k in ("stdout", "stderr")},
        }
    except TimeoutError:
        private_json(
            cwd / "process-failure.json",
            {"code": "RSI_CODEX_TIMEOUT", "timeout_seconds": timeout, "usage": "unknown"},
        )
        raise DomainError("RSI_CODEX_TIMEOUT") from None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
