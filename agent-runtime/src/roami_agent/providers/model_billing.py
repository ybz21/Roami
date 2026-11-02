"""Legacy usage records and history; all quota admission belongs to Go."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.providers.model_pricing import (
    amount,
    currency_value,
    is_zero_price,
    local_charge,
    model_prices,
)
from roami_agent.providers.model_usage import (
    USAGE_COLUMNS,
    money_records,
    row_charges,
    usage_statistics,
    usage_totals,
)


def proxy_configuration(raw=None):
    if raw is None:
        return {"dailyLimit": None, "currency": "USD", "prices": {}}
    if not isinstance(raw, dict) or set(raw) - {"dailyLimit", "currency", "prices"}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    limit = raw.get("dailyLimit")
    if limit is not None and amount(limit) <= 0:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    currency = currency_value(raw.get("currency", "CNY"))
    return {
        "dailyLimit": limit,
        "currency": currency,
        "prices": model_prices(raw.get("prices", {}), currency),
    }


def usage_counts(raw):
    if not isinstance(raw, dict):
        return None
    responses = "input_tokens" in raw or "output_tokens" in raw
    details = raw.get("input_tokens_details" if responses else "prompt_tokens_details") or {}
    if not isinstance(details, dict):
        return None
    counts = (
        raw.get("input_tokens" if responses else "prompt_tokens"),
        raw.get("output_tokens" if responses else "completion_tokens"),
        details.get("cached_tokens", 0),
    )
    if any(type(value) is not int or not 0 <= value <= 100_000_000 for value in counts):
        return None
    return counts if counts[2] <= counts[0] else None


class ModelBilling:
    def __init__(self, database, configuration, timezone, *, clock=now_ms):
        self.db, self.configuration, self.timezone = database, configuration, timezone
        self.clock = clock
        self.recovered = False
        self.revision = 0
        self.summary_cache = None

    def period(self):
        zone = self.timezone()
        return datetime.fromtimestamp(self.clock() / 1000, ZoneInfo(zone)).strftime(
            "%Y-%m-%d"
        ), zone

    async def recover(self):
        if not self.recovered:
            config = proxy_configuration(self.configuration())
            zero_price = {"currency": config["currency"], "input": 0, "output": 0, "cacheRead": 0}

            def recover(db):
                db.execute(
                    "UPDATE model_proxy_calls SET state='unknown',error_code='MODEL_PROXY_INTERRUPTED' WHERE state='pending'"
                )
                # Old unpriced calls must not keep the daily limit locked after upgrading.
                rows = db.execute(
                    "SELECT id,prices_json FROM model_proxy_calls WHERE cost_source='unknown' AND cost_amount IS NULL AND state!='pending'"
                ).fetchall()
                for row in rows:
                    rate = json.loads(row["prices_json"]) if row["prices_json"] else zero_price
                    if is_zero_price(rate):
                        rate = {"currency": "CNY", "cacheRead": None, **rate}
                        db.execute(
                            "UPDATE model_proxy_calls SET state=CASE WHEN state='unknown' THEN 'known' ELSE state END,prices_json=?,cost_amount='0',cost_currency=?,cost_source='estimate' WHERE id=?",
                            (json.dumps(rate), rate["currency"], row["id"]),
                        )

            await self.db.call(recover, write=True)
            self.recovered = True
            self.revision += 1

    async def daily_summary(self):
        day, zone = self.period()
        key = (day, zone, self.revision)
        if self.summary_cache is not None and self.summary_cache[0] == key:
            return self.summary_cache[1]

        def read(db):
            total = db.execute(
                f"SELECT {USAGE_COLUMNS} FROM model_proxy_calls WHERE day=?", (day,)
            ).fetchone()
            return {
                "day": day,
                "timezone": zone,
                **usage_totals(total),
                **money_records(db, "day=?", [day])["total"],
            }

        value = await self.db.call(read)
        if self.revision == key[2]:
            self.summary_cache = (key, value)
        return value

    async def admit(self, role, model):
        config = proxy_configuration(self.configuration())
        day, zone = self.period()
        call_id, started = identity(), self.clock()

        def insert(db):
            db.execute(
                "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,prices_json) VALUES(?,?,?,?,?,?,'pending',?)",
                (
                    call_id,
                    day,
                    zone,
                    role,
                    model,
                    started,
                    json.dumps(
                        config["prices"].get(
                            model,
                            {
                                "currency": config["currency"],
                                "input": 0,
                                "output": 0,
                                "cacheRead": 0,
                            },
                        )
                    ),
                ),
            )

        await self.db.call(insert, write=True)
        self.revision += 1
        return call_id

    async def settle(
        self, call_id, counts, *, charge=None, failed=False, not_sent=False, error=None
    ):
        def write(db):
            row = db.execute(
                "SELECT state,prices_json FROM model_proxy_calls WHERE id=?", (call_id,)
            ).fetchone()
            if row is None or row["state"] != "pending":
                return
            receipt = charge
            source = "upstream" if receipt is not None else "not_sent" if not_sent else "unknown"
            if receipt is None and not not_sent and row["prices_json"]:
                rate = json.loads(row["prices_json"])
                if is_zero_price(rate) or (counts is not None and not failed):
                    receipt = local_charge(rate, counts or (0, 0, 0))
                    source = "estimate"
            state = "failed" if failed else "known" if receipt is not None else "unknown"
            db.execute(
                "UPDATE model_proxy_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_amount=?,cost_currency=?,cost_source=?,error_code=? WHERE id=? AND state='pending'",
                (
                    state,
                    self.clock(),
                    *(counts or (None, None, None)),
                    format(receipt.amount, "f") if receipt is not None else None,
                    receipt.currency if receipt is not None else None,
                    source,
                    error,
                    call_id,
                ),
            )

        await self.db.call(write, write=True)
        self.revision += 1

    async def view(self, *, days=7, day=None):
        today, zone = self.period()
        selected = day or today
        if day is not None:
            try:
                if date.fromisoformat(day).isoformat() != day or day > today:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise DomainError("INVALID_MODEL_USAGE_DAY") from error
            days = 1

        def read(db):
            total = db.execute(
                f"SELECT {USAGE_COLUMNS} FROM model_proxy_calls WHERE day=?", (today,)
            ).fetchone()
            costs = money_records(db, "day=?", [today])
            recent = db.execute(
                "SELECT id,role,model,started_ms,state,input_tokens,output_tokens,cache_read_tokens,cost_nano,cost_amount,cost_currency,cost_source,error_code FROM model_proxy_calls WHERE day=? ORDER BY started_ms DESC,id DESC LIMIT 20",
                (today,),
            ).fetchall()
            return {
                "day": today,
                "timezone": zone,
                **usage_totals(total),
                **costs["total"],
                "statistics": usage_statistics(db, selected, days),
                "recent": [{**dict(row), **row_charges(row)} for row in recent],
            }

        return await self.db.call(read)
