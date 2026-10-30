"""An operation-local text bridge from Codex to the configured Go model connection."""

import asyncio
import hmac
import json
import secrets
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict, dataclass

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.integrations.codex_responses import TextResponse, text_messages
from roami_agent.improvement.integrations.measurements import EpisodeBudget
from roami_agent.improvement.integrations.model_gateway import MAX_HEADER_BYTES, MAX_REQUEST_BYTES
from roami_agent.improvement.integrations.request_model import RequestBudgetModel
from roami_agent.protocol.errors import DomainError, public_error_code


@dataclass
class CodexGatewayPlan:
    settings: object
    route: object
    model: str
    factory: object = None

    @property
    def identity(self):
        return digest(["codex-text-go-v2-configured-model", self.model, asdict(self.route)])


async def gateway_plan(settings, selected, *, factory=None):
    model = selected.get("model")
    require(isinstance(model, str) and 0 < len(model) <= 200, "RSI_CODEX_MODEL_REQUIRED")
    route = settings.route("main")
    require(bool(route.endpoint and route.name), "RSI_CODEX_SHARED_GATEWAY_REQUIRED")
    # The CLI model identifies its wire protocol; the node owns upstream selection.
    return CodexGatewayPlan(settings, route, model, factory)


@asynccontextmanager
async def gateway_route(plan, selected, env, role, *, outcome, seconds, observation_id=None):
    async with CodexTextGateway(
        plan, role, outcome, seconds, observation_id=observation_id
    ) as bridge:
        prefix = "model_providers.roami_rsi_go."
        routed = {
            k: v
            for k, v in selected.items()
            if not k.startswith("model_providers.") and k != "model_provider"
        }
        routed.update(
            {
                "model_provider": "roami_rsi_go",
                prefix + "name": "Roami RSI Go gateway",
                prefix + "base_url": bridge.url,
                prefix + "wire_api": "responses",
                prefix + "env_key": "ROAMI_RSI_CODEX_GATEWAY_KEY",
                prefix + "requires_openai_auth": False,
                prefix + "supports_websockets": False,
                prefix + "request_max_retries": 0,
                prefix + "stream_max_retries": 0,
            }
        )
        # The child receives a one-operation credential, never the Go or personal provider key.
        allowed = {
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "CODEX_HOME",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
        }
        environment = {k: v for k, v in env.items() if k in allowed}
        environment["ROAMI_RSI_CODEX_GATEWAY_KEY"] = bridge.secret
        environment["NO_PROXY"] = ",".join(
            filter(None, [environment.get("NO_PROXY"), "127.0.0.1", "localhost", "::1"])
        )
        try:
            yield routed, environment
        finally:
            outcome["gateway"] = {
                "identity": plan.identity,
                "model": plan.model,
                "gateway_model": plan.route.name,
                "transport": "local_go_gateway",
            }


class CodexTextGateway:
    def __init__(self, plan, role, outcome, seconds, *, observation_id=None):
        self.plan, self.role, self.outcome = plan, role, outcome
        self.secret = secrets.token_hex(32)
        self.budget = EpisodeBudget(
            {"seconds": seconds}, shared_daily_limit=True, observation_id=observation_id
        )
        self.journal, self.clients, self.errors = [], set(), []
        self.accepted = False

    async def __aenter__(self):
        self.server = await asyncio.start_server(
            self.handle, "127.0.0.1", 0, limit=MAX_HEADER_BYTES
        )
        self.url = "http://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        clients = list(self.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        requests = []
        for item in self.journal:
            usage = [e["value"] for e in item["events"] if e["kind"] == "usage"]
            requests.append(
                {
                    "model": item["model"],
                    "role": item["role"],
                    "observation_id": item["observation_id"],
                    "request_id": item["request_id"],
                    "measurement": item["measurement"],
                    "usage": usage[-1] if usage else None,
                    "error_code": public_error_code(item.get("error_code")),
                }
            )
        self.outcome.update(metrics=self.budget.metrics(), requests=requests, errors=self.errors)
        self.outcome["admission_rejected"] = bool(self.journal) and all(
            item.get("admission_rejected") is True
            and not any(e["kind"] in {"text", "tool", "usage"} for e in item["events"])
            for item in self.journal
        )

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        response = None
        authenticated = False
        try:
            async with asyncio.timeout(20):
                raw = (await reader.readuntil(b"\r\n\r\n")).decode("latin1").split("\r\n")
                method, path, _ = raw[0].split(" ")
                headers = {}
                for line in raw[1:]:
                    if not line:
                        continue
                    key, sep, value = line.partition(":")
                    require(sep and key.lower() not in headers, "RSI_CODEX_GATEWAY_INPUT")
                    headers[key.lower()] = value.strip()
                require(
                    hmac.compare_digest(headers.get("authorization", ""), "Bearer " + self.secret),
                    "RSI_CODEX_GATEWAY_AUTH",
                )
                authenticated = True
                require(
                    method == "POST" and path in {"/responses", "/v1/responses"},
                    "RSI_CODEX_GATEWAY_ROUTE",
                )
                length = headers.get("content-length", "")
                require(
                    "transfer-encoding" not in headers
                    and length.isdigit()
                    and 0 < int(length) <= MAX_REQUEST_BYTES,
                    "RSI_CODEX_GATEWAY_SIZE",
                )
                body = json.loads(await reader.readexactly(int(length)))
                messages = text_messages(body, self.plan.model)
                reasoning = body.get("reasoning") or {}
                require(isinstance(reasoning, dict), "RSI_CODEX_GATEWAY_INPUT")
                maximum = body.get("max_output_tokens")
                require(
                    maximum is None or type(maximum) is int and maximum > 0,
                    "RSI_CODEX_GATEWAY_INPUT",
                )
                require(not self.accepted, "RSI_CODEX_SINGLE_TURN_REQUIRED")
                self.accepted = True
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            response = TextResponse(writer, self.plan.model)
            await response.start()
            model = RequestBudgetModel(
                self.plan.settings,
                self.plan.route,
                self.budget,
                "main",
                factory=self.plan.factory,
                journal=self.journal,
                observation_role="rsi_codex_" + self.role,
            )
            usage = {}
            async with aclosing(model.stream(messages, [])) as events:
                async for event in events:
                    if event.kind == "text":
                        await response.delta(event.value)
                    elif event.kind == "usage":
                        usage = event.value
                    require(event.kind != "tool", "RSI_UNEXPECTED_MODEL_TOOL")
            require(self.budget.metrics()["tokens"] is not None, "RSI_USAGE_UNKNOWN")
            await response.complete(usage)
        except (
            DomainError,
            OSError,
            ValueError,
            TypeError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
        ) as error:
            code = (
                (public_error_code(error.code) or "RSI_CODEX_GATEWAY_FAILED")
                if isinstance(error, DomainError)
                else "RSI_CODEX_GATEWAY_FAILED"
            )
            if authenticated:
                self.errors.append(code)
                self.outcome.setdefault("error_code", code)
            try:
                if response:
                    await response.failed(code)
                else:
                    data = json.dumps({"error": {"code": code, "message": code}}).encode()
                    writer.write(
                        b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
                        + data
                    )
                    await writer.drain()
            except OSError:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.clients.discard(task)


def gateway_metrics(outcome, cli):
    metrics = outcome["metrics"]
    require(metrics["tokens"] is not None and metrics["model_calls"] > 0, "RSI_USAGE_UNKNOWN")
    requests = outcome["requests"]
    cached = [(item.get("usage") or {}).get("cacheReadTokens") for item in requests]
    return {
        **cli,
        **{
            key: metrics[key]
            for key in ("tokens", "model_calls", "request_attempts", "token_coverage")
        },
        "input_tokens": sum(item["measurement"]["inputTokens"] for item in requests),
        "output_tokens": sum(item["measurement"]["outputTokens"] for item in requests),
        "cached_input_tokens": sum(cached) if all(type(v) is int for v in cached) else None,
        "usage_scope": "host_go_gateway",
    }
