"""Node-local CNY accounting; unknown provider charges remain unknown."""

import json
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.providers.model_usage import usage_statistics

NANO = 1_000_000_000
PRICE_FIELDS = {"input", "output", "cacheRead"}


def amount(value):
    if type(value) not in {int, float}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= 1_000_000 or number.as_tuple().exponent < -6:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    return number


def proxy_configuration(raw=None):
    if raw is None:
        return {"dailyLimit": None, "prices": {}}
    if not isinstance(raw, dict) or set(raw) - {"dailyLimit", "prices"}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    limit = raw.get("dailyLimit")
    if limit is not None and amount(limit) <= 0:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    prices = raw.get("prices", {})
    if not isinstance(prices, dict) or len(prices) > 32:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    for model, rate in prices.items():
        if (
            not isinstance(model, str)
            or not model.strip()
            or len(model) > 200
            or any(ord(char) < 32 for char in model)
            or not isinstance(rate, dict)
            or set(rate) != PRICE_FIELDS
        ):
            raise DomainError("INVALID_MODEL_PROXY_CONFIG")
        for value in rate.values():
            amount(value)
    return {"dailyLimit": limit, "prices": prices}


def usage_counts(raw):
    if not isinstance(raw, dict):
        return None
    details = raw.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        return None
    counts = (
        raw.get("prompt_tokens"),
        raw.get("completion_tokens"),
        details.get("cached_tokens", 0),
    )
    if any(type(value) is not int or not 0 <= value <= 100_000_000 for value in counts):
        return None
    return counts if counts[2] <= counts[0] else None


def cost_nano(prices, counts):
    prompt, output, cached = counts
    # OpenAI includes cache hits in prompt_tokens; charge each input token once.
    total = (
        Decimal(prompt - cached) * amount(prices["input"])
        + Decimal(output) * amount(prices["output"])
        + Decimal(cached) * amount(prices["cacheRead"])
    ) * 1000
    return int(total.to_integral_value(rounding=ROUND_CEILING))


class ModelBilling:
    def __init__(self, database, configuration, timezone, *, clock=now_ms):
        self.db, self.configuration, self.timezone = database, configuration, timezone
        self.clock = clock
        self.recovered = False

    def period(self):
        zone = self.timezone()
        return datetime.fromtimestamp(self.clock() / 1000, ZoneInfo(zone)).strftime(
            "%Y-%m-%d"
        ), zone

    async def recover(self):
        if not self.recovered:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE model_proxy_calls SET state='unknown',error_code='MODEL_PROXY_INTERRUPTED' WHERE state='pending'"
                ),
                write=True,
            )
            self.recovered = True

    async def admit(self, role, model):
        config = proxy_configuration(self.configuration())
        day, zone = self.period()
        configured = config["prices"].get(model)
        prices = dict(configured) if configured is not None else None
        call_id, started = identity(), self.clock()

        def insert(db):
            if config["dailyLimit"] is not None:
                if prices is None:
                    raise DomainError("MODEL_PROXY_PRICE_REQUIRED", 409)
                current = db.execute(
                    "SELECT COALESCE(SUM(cost_nano),0),SUM(state IN ('pending','unknown')) FROM model_proxy_calls WHERE day=?",
                    (day,),
                ).fetchone()
                if current[1]:
                    raise DomainError("MODEL_PROXY_USAGE_UNKNOWN", 409)
                if current[0] >= amount(config["dailyLimit"]) * NANO:
                    raise DomainError("MODEL_PROXY_DAILY_LIMIT", 409)
            db.execute(
                "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,prices_json) VALUES(?,?,?,?,?,?,'pending',?)",
                (
                    call_id,
                    day,
                    zone,
                    role,
                    model,
                    started,
                    json.dumps(prices) if prices is not None else None,
                ),
            )

        await self.db.call(insert, write=True)
        return call_id, prices

    async def settle(self, call_id, prices, counts, *, failed=False, error=None):
        cost = cost_nano(prices, counts) if prices is not None and counts is not None else None
        state = "failed" if failed else "known" if cost is not None else "unknown"
        await self.db.call(
            lambda db: db.execute(
                "UPDATE model_proxy_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_nano=?,error_code=? WHERE id=? AND state='pending'",
                (
                    state,
                    self.clock(),
                    *(counts or (None, None, None)),
                    0 if failed else cost,
                    error,
                    call_id,
                ),
            ),
            write=True,
        )

    async def view(self, *, days=7):
        day, zone = self.period()

        def read(db):
            total = db.execute(
                "SELECT COUNT(*) AS requests,COALESCE(SUM(cost_nano),0) AS cost,SUM(state='unknown') AS unknown,SUM(state='pending') AS pending,COALESCE(SUM(input_tokens),0) AS input,COALESCE(SUM(output_tokens),0) AS output,COALESCE(SUM(cache_read_tokens),0) AS cache FROM model_proxy_calls WHERE day=?",
                (day,),
            ).fetchone()
            recent = db.execute(
                "SELECT id,role,model,started_ms,state,input_tokens,output_tokens,cache_read_tokens,cost_nano,error_code FROM model_proxy_calls WHERE day=? ORDER BY started_ms DESC,id DESC LIMIT 20",
                (day,),
            ).fetchall()
            return {
                "day": day,
                "timezone": zone,
                "currency": "CNY",
                "statistics": usage_statistics(db, day, days),
                "requests": total["requests"],
                "knownCost": total["cost"] / NANO,
                "unknown": total["unknown"] or 0,
                "pending": total["pending"] or 0,
                "inputTokens": total["input"],
                "outputTokens": total["output"],
                "cacheReadTokens": total["cache"],
                "recent": [
                    {
                        **dict(row),
                        "cost": row["cost_nano"] / NANO if row["cost_nano"] is not None else None,
                    }
                    for row in recent
                ],
            }

        return await self.db.call(read)
