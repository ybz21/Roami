"""Upstream charges, configured fallback pricing and node-local daily admission."""

import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.providers.model_pricing import amount, currency_value, local_charge, model_prices
from roami_agent.providers.model_usage import (
    USAGE_COLUMNS,
    money_records,
    row_charges,
    usage_statistics,
    usage_totals,
)
from roami_agent.providers.upstream_costs import add_amounts


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
        call_id, started = identity(), self.clock()

        def insert(db):
            if config["dailyLimit"] is not None:
                spent = Decimal(0)
                for row in db.execute(
                    "SELECT state,cost_source,cost_amount,cost_currency FROM model_proxy_calls WHERE day=?",
                    (day,),
                ):
                    billable = (
                        row["cost_source"] in {"upstream", "estimate"}
                        and row["cost_amount"] is not None
                    )
                    if row["state"] == "pending" or not (
                        billable or row["cost_source"] == "not_sent"
                    ):
                        raise DomainError("MODEL_PROXY_USAGE_UNKNOWN", 409)
                    if billable:
                        if row["cost_currency"] != config["currency"]:
                            raise DomainError("MODEL_PROXY_CURRENCY_MISMATCH", 409)
                        spent = add_amounts(spent, Decimal(row["cost_amount"]))
                if spent >= amount(config["dailyLimit"]):
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
                    json.dumps(config["prices"][model]) if model in config["prices"] else None,
                ),
            )

        await self.db.call(insert, write=True)
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
            if (
                receipt is None
                and counts is not None
                and not failed
                and not not_sent
                and row["prices_json"]
            ):
                receipt = local_charge(json.loads(row["prices_json"]), counts)
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
