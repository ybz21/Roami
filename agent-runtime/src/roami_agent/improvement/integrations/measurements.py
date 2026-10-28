"""Episode-wide accounting includes workers, retries and maintenance models."""

import asyncio
import json
import time

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.integrations.input_reservation import InputReservation
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.protocol.identity import identity
from roami_agent.protocol.model_observation import model_observation


class BudgetAdmissionRejected(ModelAdmissionRejected):
    """No provider request was sent by this admission attempt."""


class EpisodeBudget:
    def __init__(self, limits, *, observation_id=None, shared_daily_limit=False):
        self.limits = limits
        self.shared_daily_limit = shared_daily_limit or uses_shared_model_limit()
        self.enforce_tokens = not self.shared_daily_limit
        self.observation_id = observation_id or "rsi-" + identity()
        self.started = time.monotonic()
        self.requests = []
        self.lock = asyncio.Lock()
        self.unknown = False
        self.reserved = 0
        self.used = 0

    def check(self):
        if time.monotonic() - self.started >= self.limits["seconds"]:
            raise BudgetAdmissionRejected("RSI_TIME_BUDGET")
        if self.unknown:
            raise BudgetAdmissionRejected("RSI_USAGE_UNKNOWN")

    async def admit(self, messages, tools, output_cap, *, input_reserve=None):
        async with self.lock:
            self.check()
            if not self.shared_daily_limit and len(self.requests) >= self.limits["requests"]:
                raise BudgetAdmissionRejected("RSI_REQUEST_BUDGET")
            # This is a conservative local admission estimate, not provider billing.
            if input_reserve is None:
                input_reserve = (
                    len(json.dumps([messages, tools], ensure_ascii=False).encode()) + 4096
                )
            require(type(input_reserve) is int and input_reserve >= 4096)
            estimate = input_reserve + output_cap
            if (
                not self.shared_daily_limit
                and self.used + self.reserved + estimate > self.limits["tokens"]
            ):
                raise BudgetAdmissionRejected("RSI_TOKEN_BUDGET")
            entry = {
                "inputTokens": None,
                "outputTokens": None,
                "requestAttempts": None,
                "retryUsageKnown": False,
                "elapsedMs": None,
                "role": None,
            }
            self.requests.append(entry)
            self.reserved += estimate
            return entry, estimate

    async def settle(self, entry, estimate, usage, elapsed):
        async with self.lock:
            self.reserved -= estimate
            entry.update({k: usage.get(k) for k in entry if k not in {"elapsedMs", "role"}})
            entry["elapsedMs"] = round(elapsed * 1000, 3)
            known = all(
                type(entry[k]) is int and entry[k] >= 0
                for k in ("inputTokens", "outputTokens", "requestAttempts")
            )
            known = known and entry["retryUsageKnown"] is True
            if not known:
                self.unknown = True
            else:
                self.used += entry["inputTokens"] + entry["outputTokens"]
                if not self.shared_daily_limit and self.used > self.limits["tokens"]:
                    raise DomainError("RSI_TOKEN_BUDGET")

    def metrics(self):
        known = not self.unknown and all(r["elapsedMs"] is not None for r in self.requests)
        return {
            "tokens": self.used if known else None,
            "token_coverage": "complete" if known else "unknown",
            "model_calls": len(self.requests),
            "request_attempts": sum(r["requestAttempts"] or 0 for r in self.requests)
            if known
            else None,
            "retries": sum(max(0, (r["requestAttempts"] or 1) - 1) for r in self.requests),
            "model_ms": sum(r["elapsedMs"] or 0 for r in self.requests),
            "requests": self.requests,
            "token_basis": "input_plus_output; cache/reasoning are subsets, not added",
        }


class MeteredModel:
    def __init__(
        self,
        provider,
        budget,
        role,
        *,
        output_cap=2048,
        journal=None,
        input_reserve=None,
        reservation_basis=None,
    ):
        self.provider, self.budget, self.role = provider, budget, role
        self.model = provider.model
        self.output_cap = output_cap
        self.journal = journal
        self.input_reserve, self.reservation_basis = input_reserve, reservation_basis
        self.input_reservation = InputReservation()
        if input_reserve is not None and isinstance(provider, MeteredModel):
            provider.input_reserve, provider.reservation_basis = input_reserve, reservation_basis

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def stream(self, messages, tools):
        messages, tools = json.loads(json.dumps([messages, tools], ensure_ascii=False))
        snapshot = None
        input_reserve, basis = self.input_reserve, self.reservation_basis
        if input_reserve is None:
            input_reserve, snapshot, basis = self.input_reservation.estimate(messages, tools)
        entry, estimate = await self.budget.admit(
            messages, tools, self.output_cap, input_reserve=input_reserve
        )
        entry["role"] = self.role
        started, usage = time.monotonic(), {}
        observation = model_observation.get()
        if observation is None:
            observation = {
                "session": self.budget.observation_id,
                "request": identity(),
                "role": self.role,
            }
        record = None
        if self.journal is not None:
            record = {
                "request": len(self.journal) + 1,
                "observation_id": observation["session"],
                "request_id": observation["request"],
                "model": self.model,
                "output_cap": self.output_cap,
                "input_reserve": estimate - self.output_cap,
                "reservation_basis": basis,
                "role": self.role,
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)),
                "events": [],
                "measurement": entry,
            }
            self.journal.append(record)
        stream = self.provider.stream(messages, tools)
        try:
            while True:
                token = model_observation.set(observation)
                try:
                    event = await anext(stream)
                except StopAsyncIteration:
                    break
                finally:
                    model_observation.reset(token)
                if record is not None and event.kind in {"text", "tool", "usage", "telemetry"}:
                    record["events"].append({"kind": event.kind, "value": event.value})
                if event.kind == "usage":
                    usage = dict(event.value)
                yield event
            if self.input_reserve is None:
                self.input_reservation.observe(snapshot, usage)
        except BaseException as exc:
            if isinstance(exc, ModelAdmissionRejected):
                usage = {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "requestAttempts": 0,
                    "retryUsageKnown": True,
                }
                if record is not None:
                    record["admission_rejected"] = True
            if record is not None:
                if isinstance(exc, (GeneratorExit, asyncio.CancelledError)):
                    record["termination"] = (
                        "closed" if isinstance(exc, GeneratorExit) else "cancelled"
                    )
                else:
                    record["error_code"] = getattr(exc, "code", type(exc).__name__)
            raise
        finally:
            try:
                if hasattr(stream, "aclose"):
                    token = model_observation.set(observation)
                    try:
                        await stream.aclose()
                    finally:
                        model_observation.reset(token)
            finally:
                await self.budget.settle(entry, estimate, usage, time.monotonic() - started)


def trace_metrics(trace):
    spans = trace["spans"]
    unique = {s["spanId"]: s for s in spans}
    require(len(unique) == len(spans), "RSI_DUPLICATE_SPAN")
    tools = [s for s in spans if s["name"].startswith("tool.")]
    return {
        "tool_calls": len(tools),
        "tool_failures": sum(s["state"] == "failed" for s in tools),
        "discovery_calls": sum(s["name"] == "tool.tool_list" for s in tools),
        "context_ms": sum(s["durationMs"] or 0 for s in spans if s["name"] == "context.build"),
        "tool_ms": sum(s["durationMs"] or 0 for s in tools),
        "first_committed_text_ms": trace["summary"]["firstCommittedTextMs"],
        "duration_sums_may_overlap": True,
        "trace_coverage": trace["coverage"],
    }
