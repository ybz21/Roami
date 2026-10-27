"""Codex-only RSI roles with durable JSONL evidence and non-replayable admission."""

import asyncio
import json
import os
import shutil
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from roami_agent.improvement.codex_proxy import codex_route
from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.operation_accounting import archive_rejected_admission
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
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


def completed_result(raw):
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
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
            isinstance(i, dict)
            and (
                i.get("type") in {"agent_message", "reasoning"}
                or i.get("type") == "error"
                and set(i) <= {"id", "type", "message"}
                and isinstance(i.get("message"), str)
            )
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
    require(
        all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")),
        "RSI_USAGE_UNKNOWN",
    )
    cached = usage.get("cached_input_tokens", 0)
    require(type(cached) is int and 0 <= cached <= usage["input_tokens"], "RSI_USAGE_UNKNOWN")
    return {
        "text": messages[0],
        "thread_id": threads[0],
        "diagnostics": [i["message"][:1024] for i in items if i.get("type") == "error"][:16],
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
    shared = getattr(workflow.ledger, "shared_daily_limit", False)
    require(shared or len(prompt.encode()) + 8192 <= config["model_tokens"], "RSI_TOKEN_BUDGET")
    selected, env = codex_configuration()
    request_hash = digest([action["kind"], messages, selected])
    # CLI usage is reported at turn completion, not a provider-enforced token ceiling.
    saved = await asyncio.to_thread(
        workflow.reserve_operation,
        action["owner"],
        workflow.day(action["owner"]),
        operation,
        config["model_tokens"],
    )
    if saved is not None:
        value = saved["value"]
        require(value.get("request_hash") == request_hash, "RSI_OPERATION_CONTEXT_CHANGED")
        if value.get("admission_rejected") is True:
            await asyncio.to_thread(
                archive_rejected_admission,
                workflow.ledger,
                action["owner"],
                operation,
                pipeline=hasattr(workflow, "run_id"),
            )
            saved = await asyncio.to_thread(
                workflow.reserve_operation,
                action["owner"],
                workflow.day(action["owner"]),
                operation,
                config["model_tokens"],
            )
            if saved is not None:
                require(
                    saved["value"].get("request_hash") == request_hash,
                    "RSI_OPERATION_CONTEXT_CHANGED",
                )
                if saved["value"].get("admission_rejected"):
                    raise DomainError(saved["value"]["error_code"])
                return saved["value"]
        else:
            require(
                shared or value["metrics"]["tokens"] <= config["model_tokens"],
                "RSI_CODEX_TOKEN_LIMIT_EXCEEDED",
            )
            return value
    root = (
        workflow.ledger.path.parent
        / "codex-roles"
        / digest([action["owner"], operation])
        / identity()
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not root.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
    private_json(
        root / "request.json", {"role": action["kind"], "operation": operation, "prompt": prompt}
    )
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
    started = time.monotonic()
    outcome = {}
    async with codex_route(
        getattr(workflow, "model_proxy", None), selected, env, action["kind"], outcome=outcome
    ) as (routed, environment):
        for name, value in routed.items():
            encoded = (
                "{ "
                + ", ".join(
                    json.dumps(key) + " = " + json.dumps(item) for key, item in value.items()
                )
                + " }"
                if isinstance(value, dict)
                else json.dumps(value)
            )
            args.extend(["-c", name + "=" + encoded])
        args.append("-")
        result = await runner(
            args,
            cwd=root,
            env=environment,
            timeout=config["model_seconds"],
            input_data=prompt.encode(),
            max_bytes=2_000_000,
        )
    private_json(root / "process.json", result)
    blocked = outcome.get("error_code")
    if (
        result["exitCode"] != 0
        and not outcome.get("attempts")
        and blocked
        in {"MODEL_PROXY_DAILY_LIMIT", "MODEL_PROXY_USAGE_UNKNOWN", "MODEL_PROXY_CURRENCY_MISMATCH"}
    ):
        await asyncio.to_thread(
            workflow.settle_operation,
            action["owner"],
            operation,
            {
                "value": {
                    "request_hash": request_hash,
                    "admission_rejected": True,
                    "error_code": blocked,
                    "metrics": {"tokens": 0},
                }
            },
        )
        raise DomainError(blocked)
    require(result["exitCode"] == 0, "RSI_CODEX_EXEC_FAILED")
    value = completed_result(result["stdout"])
    value["metrics"]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    value.update(
        spending_policy="shared_model_daily" if shared else "frozen_protocol",
        executor="codex",
        role=action["kind"],
        request_hash=request_hash,
        log=str(root / "process.json"),
    )
    await asyncio.to_thread(workflow.settle_operation, action["owner"], operation, {"value": value})
    require(
        shared or value["metrics"]["tokens"] <= config["model_tokens"],
        "RSI_CODEX_TOKEN_LIMIT_EXCEEDED",
    )
    return value
