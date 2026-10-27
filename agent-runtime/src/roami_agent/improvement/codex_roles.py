"""Codex-only RSI roles with durable JSONL evidence and non-replayable admission."""

import asyncio
import json
import os
import shutil
import time
import tomllib
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.executors import private_json
from roami_agent.tools.process import execute


def codex_configuration():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = home / "config.toml"
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    # Preserve model routing/authentication, without loading personal hooks, MCPs or plugins.
    selected = {
        k: config[k] for k in ("model", "model_provider", "model_reasoning_effort") if k in config
    }
    provider = config.get("model_providers", {}).get(config.get("model_provider"), {})
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
                for header, variable in value.items():
                    selected[f"model_providers.{name}.env_http_headers.{json.dumps(header)}"] = (
                        variable
                    )
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


def completed_result(raw):
    try:
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except ValueError:
        require(False, "RSI_CODEX_TURN_INCOMPLETE")
    require(
        all(isinstance(event, dict) and isinstance(event.get("type"), str) for event in events),
        "RSI_CODEX_TURN_INCOMPLETE",
    )
    threads = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
    completed = [e for e in events if e.get("type") == "turn.completed"]
    require(
        len(threads) == 1 and isinstance(threads[0], str) and bool(threads[0]),
        "RSI_CODEX_IDENTITY_REQUIRED",
    )
    require(
        len(completed) == 1 and not any(e.get("type") in {"error", "turn.failed"} for e in events),
        "RSI_CODEX_TURN_INCOMPLETE",
    )
    observed_items = [e["item"] for e in events if e.get("type", "").startswith("item.")]
    require(
        all(
            isinstance(i, dict) and i.get("type") in {"agent_message", "reasoning"}
            for i in observed_items
        ),
        "RSI_UNEXPECTED_MODEL_TOOL",
    )
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    messages = [i.get("text") for i in items if i.get("type") == "agent_message"]
    require(
        len(messages) == 1 and isinstance(messages[0], str) and len(messages[0]) <= 100000,
        "RSI_INVALID_MODEL_OUTPUT",
    )
    usage = completed[0].get("usage", {})
    require(isinstance(usage, dict), "RSI_USAGE_UNKNOWN")
    require(
        all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")),
        "RSI_USAGE_UNKNOWN",
    )
    cached = usage.get("cached_input_tokens", 0)
    require(type(cached) is int and 0 <= cached <= usage["input_tokens"], "RSI_USAGE_UNKNOWN")
    return {
        "text": messages[0],
        "thread_id": threads[0],
        "metrics": {
            "tokens": usage["input_tokens"] + usage["output_tokens"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cached_input_tokens": cached,
            "model_calls": None,
            "cli_turns": 1,
            "usage_scope": "codex_turn_reported",
            "tool_calls": 0,
        },
    }


def codex_usage(raw):
    from roami_agent.providers.model_billing import usage_counts

    try:
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        completed = [e for e in events if e.get("type") == "turn.completed"]
        if len(completed) != 1:
            return None
        usage = completed[0].get("usage", {})
        return usage_counts(
            {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "prompt_tokens_details": {"cached_tokens": usage.get("cached_input_tokens", 0)},
            }
        )
    except (ValueError, TypeError, AttributeError):
        return None


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
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def codex_json(workflow, action, config, key, messages, *, runner=run_codex):
    if runner is run_codex:
        require(shutil.which("codex") is not None, "RSI_CODEX_NOT_INSTALLED")
    if action.get("lease"):
        with workflow.ledger.connection() as db:
            workflow._owned_action(db, action)
    operation = action["id"] + ":" + key
    prompt = (
        "You are the Codex RSI "
        + action["kind"]
        + " role. Use only the supplied evidence. Do not call tools. Return the requested JSON object.\n"
        + json.dumps(messages, ensure_ascii=False)
    )
    from roami_agent.providers.model_proxy import model_proxy_context

    proxy = model_proxy_context.get()
    if proxy is None:
        require(len(prompt.encode()) + 8192 <= config["model_tokens"], "RSI_TOKEN_BUDGET")
    selected, env = codex_configuration()
    model = selected.get("model")
    if proxy is not None:
        require(isinstance(model, str) and 0 < len(model) <= 200, "RSI_CODEX_MODEL_REQUIRED")
    request_hash = digest([action["kind"], messages, selected])
    # CLI usage is reported at turn completion, not a provider-enforced token ceiling.
    saved = (
        await asyncio.to_thread(workflow.operation_result, action["owner"], operation)
        if proxy is not None
        else await asyncio.to_thread(
            workflow.reserve_operation,
            action["owner"],
            workflow.day(action["owner"]),
            operation,
            config["model_tokens"],
        )
    )
    if saved is not None:
        value = saved["value"]
        require(value.get("request_hash") == request_hash, "RSI_OPERATION_CONTEXT_CHANGED")
        require(
            proxy is not None or value["metrics"]["tokens"] <= config["model_tokens"],
            "RSI_CODEX_TOKEN_LIMIT_EXCEEDED",
        )
        return value
    root = workflow.ledger.path.parent / "codex-roles" / digest([action["owner"], operation])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not root.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
    args = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-C",
        str(root),
    ]
    selected.update(
        {
            "approval_policy": "never",
            "project_doc_max_bytes": 0,
            "web_search": "disabled",
            "features.shell_tool": False,
            "features.hooks": False,
            "features.memories": False,
            "features.multi_agent": False,
            "features.apply_patch_freeform": False,
            "features.code_mode.enabled": False,
        }
    )
    for name, value in selected.items():
        args.extend(["-c", name + "=" + json.dumps(value)])
    args.append("-")
    started = time.monotonic()
    async with (
        proxy.external_turn("worker", model) if proxy is not None else nullcontext(None)
    ) as receipt:
        if receipt is not None:
            prior = await asyncio.to_thread(
                workflow.reserve_operation,
                action["owner"],
                workflow.day(action["owner"]),
                operation,
                config["model_tokens"],
            )
            if prior is not None:
                require(
                    prior["value"].get("request_hash") == request_hash,
                    "RSI_OPERATION_CONTEXT_CHANGED",
                )
                return prior["value"]
        private_json(
            root / "request.json",
            {"role": action["kind"], "operation": operation, "prompt": prompt},
        )
        if receipt is not None:
            receipt["sent"] = True
        result = await runner(
            args,
            cwd=root,
            env=env,
            timeout=config["model_seconds"],
            input_data=prompt.encode(),
            max_bytes=2_000_000,
        )
        private_json(root / "process.json", result)
        if receipt is not None:
            receipt["counts"] = codex_usage(result["stdout"])
        require(result["exitCode"] == 0, "RSI_CODEX_EXEC_FAILED")
        value = completed_result(result["stdout"])
    value["metrics"]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    value.update(
        executor="codex",
        role=action["kind"],
        request_hash=request_hash,
        log=str(root / "process.json"),
    )
    await asyncio.to_thread(workflow.settle_operation, action["owner"], operation, {"value": value})
    require(
        proxy is not None or value["metrics"]["tokens"] <= config["model_tokens"],
        "RSI_CODEX_TOKEN_LIMIT_EXCEEDED",
    )
    return value
