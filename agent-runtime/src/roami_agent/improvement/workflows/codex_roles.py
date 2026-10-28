"""Codex-only RSI roles with durable JSONL evidence and non-replayable admission."""

import asyncio
import json
import shutil
import time

from roami_agent.improvement.domain.codex_result import completed_result
from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.integrations.codex_cli import (
    codex_configuration,
    run_codex,
)
from roami_agent.improvement.integrations.codex_proxy import codex_route
from roami_agent.improvement.integrations.spending_policy import (
    model_proxy_for,
    uses_shared_model_limit,
)
from roami_agent.improvement.persistence.operation_accounting import archive_rejected_admission
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity


async def codex_json(workflow, action, config, key, messages, *, runner=run_codex):
    if runner is run_codex:
        require(shutil.which("codex") is not None, "RSI_CODEX_NOT_INSTALLED")
    if action.get("lease"):
        workflow.assert_action_owned(action)
    operation = action["id"] + ":" + key
    prompt = (
        "You are the Codex RSI "
        + action["kind"]
        + " role. Use only the supplied evidence. Do not call tools. Return the requested JSON object.\n"
        + json.dumps(messages, ensure_ascii=False)
    )
    shared = uses_shared_model_limit(workflow.ledger)
    require(shared or len(prompt.encode()) + 8192 <= config["model_tokens"], "RSI_TOKEN_BUDGET")
    selected, env = codex_configuration()
    proxy = model_proxy_for(workflow)
    if proxy is not None:
        require(
            isinstance(selected.get("model"), str) and 0 < len(selected["model"]) <= 200,
            "RSI_CODEX_MODEL_REQUIRED",
        )

    request_hash = digest([action["kind"], messages, selected])
    # CLI usage is reported at turn completion, not a provider-enforced token ceiling.
    saved = (
        await asyncio.to_thread(workflow.operation_result, action["owner"], operation)
        if proxy is not None
        else None
    )
    if saved is None:
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
    async with codex_route(proxy, selected, env, action["kind"], outcome=outcome) as (
        routed,
        environment,
    ):
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
