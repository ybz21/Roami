"""Go gateway routing for the tool-free Codex RSI roles, without paid inference."""

import json
import os
import shutil
from dataclasses import replace

import httpx
import pytest

from roami_agent.improvement.domain.codex_result import completed_result
from roami_agent.improvement.integrations.codex_cli import run_codex
from roami_agent.improvement.integrations.codex_gateway import (
    CodexGatewayPlan,
    CodexTextGateway,
    gateway_plan,
    gateway_route,
)
from roami_agent.improvement.integrations.codex_responses import text_messages
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


def settings():
    return Settings(endpoint="https://gateway.invalid/v1", model="node-model")


class Provider:
    model = "rr/gpt-6.1-sol"

    def __init__(self, calls, *, unknown=False, tool=False, error=None):
        self.calls, self.unknown, self.tool, self.error = calls, unknown, tool, error

    async def stream(self, messages, tools):
        self.calls.append((messages, tools))
        yield ModelEvent("text", '{"document":')
        if self.error:
            raise DomainError(self.error)
        if self.tool:
            yield ModelEvent("tool", {"id": "not-allowed"})
        yield ModelEvent("text", '"fixture summary"}')
        if not self.unknown:
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 123,
                    "outputTokens": 7,
                    "cacheReadTokens": 10,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )


def plan(calls, **kwargs):
    value = settings()
    return CodexGatewayPlan(
        value,
        replace(value.route("main"), name="rr/gpt-6.1-sol"),
        "gpt-6.1-sol",
        lambda *_: Provider(calls, **kwargs),
    )


def payload():
    return {
        "model": "gpt-6.1-sol",
        "stream": True,
        "instructions": "system",
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": "rules"}]},
            {"role": "user", "content": "summarize"},
        ],
    }


@pytest.mark.parametrize(
    "names,expected",
    [
        (["rr/gpt-6.1-sol"], "rr/gpt-6.1-sol"),
        (["gpt-6.1-sol", "rr/gpt-6.1-sol"], "gpt-6.1-sol"),
        (["rr/gpt-6.1-sol", "other/gpt-6.1-sol"], None),
        (["other-model"], None),
    ],
)
async def test_model_alias_is_exact_or_unique_without_changing_the_requested_model(names, expected):
    async def catalog(endpoint, key):
        assert endpoint == "https://gateway.invalid/v1"
        return dict.fromkeys(names)

    if expected is None:
        with pytest.raises(DomainError, match="MODEL_ROUTE_REQUIRED"):
            await gateway_plan(settings(), {"model": "gpt-6.1-sol"}, catalog=catalog)
    else:
        value = await gateway_plan(
            settings(), {"model": "gpt-6.1-sol", "model_reasoning_effort": "high"}, catalog=catalog
        )
        assert value.model == "gpt-6.1-sol" and value.route.name == expected
        assert value.route.max_retries == 0 and value.route.context_window is None
        assert value.route.parameters["reasoning_effort"] == "high"


@pytest.mark.parametrize(
    "item",
    [
        {"type": "function_call", "name": "bash"},
        {"role": "user", "content": [{"type": "input_image", "image_url": "private"}]},
        {"role": "tool", "content": "result"},
    ],
)
def test_text_roles_reject_tool_or_image_input(item):
    body = payload()
    body["input"] = [item]
    with pytest.raises(DomainError):
        text_messages(body, "gpt-6.1-sol")


async def test_incremental_stream_has_terminal_usage_and_never_forwards_client_tools():
    calls, outcome = [], {}
    async with (
        CodexTextGateway(plan(calls), "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        body = payload()
        body["tools"] = [{"type": "function", "name": "bash"}]
        response = await client.post(
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json=body,
        )
    frames = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert [v["sequence_number"] for v in frames] == list(range(len(frames)))
    assert frames[0]["type"] == "response.created" and frames[-1]["type"] == "response.completed"
    assert len([v for v in frames if v["type"] == "response.output_text.delta"]) == 2
    final = frames[-1]["response"]
    assert final["usage"]["total_tokens"] == 130
    assert final["usage"]["input_tokens_details"]["cached_tokens"] == 10
    assert calls == [
        (
            [
                {"role": "system", "content": "system"},
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "summarize"},
            ],
            [],
        )
    ]
    assert outcome["metrics"]["tokens"] == 130 and outcome["metrics"]["model_calls"] == 1


@pytest.mark.parametrize(
    "options,code",
    [
        ({"unknown": True}, "RSI_USAGE_UNKNOWN"),
        ({"tool": True}, "RSI_UNEXPECTED_MODEL_TOOL"),
        ({"error": "MODEL_HTTP_402"}, "MODEL_HTTP_402"),
        ({"error": "private://credential-detail"}, "RSI_CODEX_GATEWAY_FAILED"),
    ],
)
async def test_failed_or_unmetered_stream_never_claims_completion(options, code):
    calls, outcome = [], {}
    async with (
        CodexTextGateway(plan(calls, **options), "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        response = await client.post(
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json=payload(),
        )
    assert "response.completed" not in response.text and "response.failed" in response.text
    assert code in response.text and "credential-detail" not in response.text
    assert outcome["error_code"] == code and len(calls) == 1
    if options.get("error") == "MODEL_HTTP_402":
        assert outcome["admission_rejected"] is False


async def test_unauthorized_or_unsupported_requests_cannot_reach_the_provider():
    calls, outcome = [], {}
    async with (
        CodexTextGateway(plan(calls), "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        response = await client.post(bridge.url + "/responses", json=payload())
        assert response.json()["error"]["code"] == "RSI_CODEX_GATEWAY_AUTH"
        body = {**payload(), "previous_response_id": "old"}
        response = await client.post(
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json=body,
        )
        assert response.json()["error"]["code"] == "RSI_CODEX_GATEWAY_CONTINUATION"
    assert calls == [] and outcome["metrics"]["model_calls"] == 0


async def test_ephemeral_route_keeps_gateway_keys_out_of_child_environment():
    env = {
        "PATH": os.environ["PATH"],
        "OPENAI_API_KEY": "private-key",
        "CODEX_API_KEY": "private-key",
        "CUSTOM_SECRET": "private-key",
        "NO_PROXY": "example.invalid",
    }
    outcome = {}
    async with gateway_route(
        plan([]),
        {
            "model": "gpt-6.1-sol",
            "model_provider": "personal",
            "model_providers.personal.base_url": "https://personal.invalid",
        },
        env,
        "review",
        outcome=outcome,
        seconds=30,
    ) as (selected, child):
        assert selected["model"] == "gpt-6.1-sol"
        assert not any("personal" in key for key in selected)
        assert all("private-key" != value for value in child.values())
        assert "localhost" in child["NO_PROXY"] and "127.0.0.1" in child["NO_PROXY"]
        assert child["ROAMI_RSI_CODEX_GATEWAY_KEY"]


@pytest.mark.parametrize(
    "fields",
    [
        {"background": True},
        {"store": True},
        {"text": {"format": {"type": "json_schema"}}},
        {"tool_choice": {"type": "function", "name": "bash"}},
    ],
)
def test_text_role_rejects_unsupported_protocol_requests(fields):
    with pytest.raises(DomainError):
        text_messages({**payload(), **fields}, "gpt-6.1-sol")


def test_tool_catalog_declaration_does_not_become_a_tool_call():
    body = payload()
    body["input"].insert(0, {"type": "additional_tools", "role": "developer", "tools": []})
    assert text_messages(body, "gpt-6.1-sol")[-1] == {"role": "user", "content": "summarize"}


@pytest.mark.skipif(
    shutil.which("codex") is None, reason="Installed Codex CLI required; no external inference"
)
async def test_real_codex_cli_completes_through_scripted_gateway(tmp_path):
    calls, outcome = [], {}
    selected = {
        "model": "gpt-6.1-sol",
        "approval_policy": "never",
        "project_doc_max_bytes": 0,
        "web_search": "disabled",
        "features.shell_tool": False,
        "features.hooks": False,
        "features.multi_agent": False,
        "features.apply_patch_freeform": False,
        "features.memories": False,
        "features.code_mode.enabled": False,
    }
    home = tmp_path / "codex-home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CODEX_HOME": str(home)}
    async with gateway_route(plan(calls), selected, env, "review", outcome=outcome, seconds=30) as (
        routed,
        child,
    ):
        argv = [
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
            str(tmp_path),
        ]
        for key, value in routed.items():
            argv.extend(["-c", key + "=" + json.dumps(value)])
        argv.append("-")
        result = await run_codex(
            argv,
            cwd=tmp_path,
            env=child,
            timeout=30,
            max_bytes=2_000_000,
            input_data=b"Return JSON only. Do not call tools.",
        )
    assert result["exitCode"] == 0, result["stderr"]
    value = completed_result(result["stdout"])
    assert value["text"] == '{"document":"fixture summary"}'
    assert value["metrics"]["tokens"] == 130 and len(calls) == 1
    assert outcome["metrics"]["tokens"] == 130
