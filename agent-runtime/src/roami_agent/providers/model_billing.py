"""Provider-reported charges and node-local daily admission; estimates are historical only."""

import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.providers.model_usage import (
    USAGE_COLUMNS,
    money_records,
    row_charges,
    usage_statistics,
    usage_totals,
)
from roami_agent.providers.upstream_costs import add_amounts


def amount(value):
    if type(value) not in {int, float}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= 1_000_000 or number.as_tuple().exponent < -6:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    return number


def proxy_configuration(raw=None):
    if raw is None:
        return {"dailyLimit": None, "currency": "USD"}
    if not isinstance(raw, dict) or set(raw) - {"dailyLimit", "currency", "prices"}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    # Legacy price tables are ignored; retained files must not restart local estimation.
    if "prices" in raw and (not isinstance(raw["prices"], dict) or len(raw["prices"]) > 32):
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    limit = raw.get("dailyLimit")
    if limit is not None and amount(limit) <= 0:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    currency = raw.get("currency", "CNY")
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    return {"dailyLimit": limit, "currency": currency}


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
                    if row["state"] == "pending" or row["cost_source"] not in {
                        "upstream",
                        "not_sent",
                    }:
                        raise DomainError("MODEL_PROXY_USAGE_UNKNOWN", 409)
                    if row["cost_source"] == "upstream":
                        if row["cost_currency"] != config["currency"]:
                            raise DomainError("MODEL_PROXY_CURRENCY_MISMATCH", 409)
                        spent = add_amounts(spent, Decimal(row["cost_amount"]))
                if spent >= amount(config["dailyLimit"]):
                    raise DomainError("MODEL_PROXY_DAILY_LIMIT", 409)
            db.execute(
                "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state) VALUES(?,?,?,?,?,?,'pending')",
                (call_id, day, zone, role, model, started),
            )

        await self.db.call(insert, write=True)
        return call_id

    async def settle(
        self, call_id, counts, *, charge=None, failed=False, not_sent=False, error=None
    ):
        source = "upstream" if charge is not None else "not_sent" if not_sent else "unknown"
        state = "failed" if failed else "known" if charge is not None else "unknown"
        await self.db.call(
            lambda db: db.execute(
                "UPDATE model_proxy_calls SET state=?,finished_ms=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cost_amount=?,cost_currency=?,cost_source=?,error_code=? WHERE id=? AND state='pending'",
                (
                    state,
                    self.clock(),
                    *(counts or (None, None, None)),
                    format(charge.amount, "f") if charge is not None else None,
                    charge.currency if charge is not None else None,
                    source,
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
                f"SELECT {USAGE_COLUMNS} FROM model_proxy_calls WHERE day=?", (day,)
            ).fetchone()
            costs = money_records(db, "day=?", [day])
            recent = db.execute(
                "SELECT id,role,model,started_ms,state,input_tokens,output_tokens,cache_read_tokens,cost_nano,cost_amount,cost_currency,cost_source,error_code FROM model_proxy_calls WHERE day=? ORDER BY started_ms DESC,id DESC LIMIT 20",
                (day,),
            ).fetchall()
            return {
                "day": day,
                "timezone": zone,
                **usage_totals(total),
                **costs["total"],
                "statistics": usage_statistics(db, day, days),
                "recent": [{**dict(row), **row_charges(row)} for row in recent],
            }

        return await self.db.call(read)
