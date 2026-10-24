"""Episode-wide accounting includes workers, retries and maintenance models."""

import asyncio
import json
import time

from roami_agent.improvement.contracts import require
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity
from roami_agent.protocol.model_observation import model_observation


class EpisodeBudget:
    def __init__(self, limits, *, observation_id=None):
        self.limits = limits
        self.observation_id = observation_id or "rsi-" + identity()
        self.started = time.monotonic()
        self.requests = []
        self.lock = asyncio.Lock()
        self.unknown = False
        self.reserved = 0
        self.used = 0

    def check(self):
        if time.monotonic() - self.started >= self.limits["seconds"]:
            raise DomainError("RSI_TIME_BUDGET")
        if self.unknown:
            raise DomainError("RSI_USAGE_UNKNOWN")

    async def admit(self, messages, tools, output_cap):
        async with self.lock:
            self.check()
            if len(self.requests) >= self.limits["requests"]:
                raise DomainError("RSI_REQUEST_BUDGET")
            # This is a conservative local admission estimate, not provider billing.
            estimate = (
                len(json.dumps([messages, tools], ensure_ascii=False).encode()) + 4096 + output_cap
            )
            if self.used + self.reserved + estimate > self.limits["tokens"]:
                raise DomainError("RSI_TOKEN_BUDGET")
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
                if self.used > self.limits["tokens"]:
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
    def __init__(self, provider, budget, role, *, output_cap=2048, journal=None):
        self.provider, self.budget, self.role = provider, budget, role
        self.model = provider.model
        self.output_cap = output_cap
        self.journal = journal

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def stream(self, messages, tools):
        entry, estimate = await self.budget.admit(messages, tools, self.output_cap)
        entry["role"] = self.role
        started, usage = time.monotonic(), {}
        observation = model_observation.get()
        observation_token = None
        if observation is None:
            observation = {
                "session": self.budget.observation_id,
                "request": identity(),
                "role": self.role,
            }
            observation_token = model_observation.set(observation)
        record = None
        if self.journal is not None:
            record = {
                "request": len(self.journal) + 1,
                "observation_id": observation["session"],
                "request_id": observation["request"],
                "model": self.model,
                "role": self.role,
                "messages": json.loads(json.dumps(messages)),
                "tools": json.loads(json.dumps(tools)),
                "events": [],
                "measurement": entry,
            }
            self.journal.append(record)
        try:
            async for event in self.provider.stream(messages, tools):
                if record is not None and event.kind in {"text", "tool", "usage", "telemetry"}:
                    record["events"].append({"kind": event.kind, "value": event.value})
                if event.kind == "usage":
                    usage = dict(event.value)
                yield event
        except BaseException as exc:
            if record is not None:
                record["error_code"] = getattr(exc, "code", type(exc).__name__)
            raise
        finally:
            try:
                await self.budget.settle(entry, estimate, usage, time.monotonic() - started)
            finally:
                if observation_token is not None:
                    model_observation.reset(observation_token)


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
