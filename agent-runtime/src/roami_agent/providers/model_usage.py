"""Daily and per-model token counts, with exact fees grouped by currency and source."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.upstream_costs import add_amounts

USAGE_COLUMNS = """
COUNT(*) AS requests,
COALESCE(SUM(state!='pending' AND cost_source IN ('unknown','estimate')),0) AS unknown,
COALESCE(SUM(state='pending'),0) AS pending,
COALESCE(SUM(state='failed'),0) AS failed,
COALESCE(SUM(cost_source='estimate'),0) AS estimated,
COALESCE(SUM(state!='pending' AND cost_source!='not_sent' AND (input_tokens IS NULL OR output_tokens IS NULL)),0) AS missing_usage,
COALESCE(SUM(input_tokens),0) AS input,
COALESCE(SUM(output_tokens),0) AS output,
COALESCE(SUM(cache_read_tokens),0) AS cache
"""


def usage_totals(row):
    return {
        "requests": row["requests"],
        "unknown": row["unknown"],
        "pending": row["pending"],
        "failed": row["failed"],
        "estimated": row["estimated"],
        "missingUsage": row["missing_usage"],
        "inputTokens": row["input"],
        "outputTokens": row["output"],
        "cacheReadTokens": row["cache"],
        "totalTokens": row["input"] + row["output"],
    }


def charge_list(amounts):
    return [
        {"currency": currency, "amount": format(amount, "f")}
        for currency, amount in sorted(amounts.items())
    ]


def row_charges(row):
    actual, estimated = {}, {}
    if row["cost_source"] == "upstream":
        actual[row["cost_currency"]] = Decimal(row["cost_amount"])
    elif row["cost_source"] == "estimate" and row["cost_nano"] is not None:
        estimated["CNY"] = Decimal(row["cost_nano"]) / 1_000_000_000
    return {"charges": charge_list(actual), "estimatedCharges": charge_list(estimated)}


def add_row_charges(group, row):
    charges = row_charges(row)
    for amounts, key in zip(group, ("charges", "estimatedCharges"), strict=True):
        for charge in charges[key]:
            currency = charge["currency"]
            amounts[currency] = add_amounts(
                amounts.get(currency, Decimal(0)), Decimal(charge["amount"])
            )


def hourly_statistics(db, day, fields):
    hours = [{"hour": hour, **dict.fromkeys(fields, 0)} for hour in range(24)]
    fees = [({}, {}) for _ in hours]
    for row in db.execute("SELECT * FROM model_proxy_calls WHERE day=?", (day,)):
        hour = datetime.fromtimestamp(row["started_ms"] / 1000, ZoneInfo(row["timezone"])).hour
        source, state = row["cost_source"], row["state"]
        counts = {
            "requests": 1,
            "unknown": int(state != "pending" and source in {"unknown", "estimate"}),
            "pending": int(state == "pending"),
            "failed": int(state == "failed"),
            "estimated": int(source == "estimate"),
            "missingUsage": int(
                state != "pending"
                and source != "not_sent"
                and (row["input_tokens"] is None or row["output_tokens"] is None)
            ),
            "inputTokens": row["input_tokens"] or 0,
            "outputTokens": row["output_tokens"] or 0,
            "cacheReadTokens": row["cache_read_tokens"] or 0,
            "totalTokens": (row["input_tokens"] or 0) + (row["output_tokens"] or 0),
        }
        for field, value in counts.items():
            hours[hour][field] += value
        add_row_charges(fees[hour], row)
    return [
        {**row, "charges": charge_list(fee[0]), "estimatedCharges": charge_list(fee[1])}
        for row, fee in zip(hours, fees, strict=True)
    ]


def money_records(db, where, parameters, *, models=(), daily_start=None):
    total, by_model, by_day = ({}, {}), {}, {}
    for row in db.execute(
        f"SELECT model,day,cost_source,cost_amount,cost_currency,cost_nano FROM model_proxy_calls WHERE {where} AND cost_source IN ('upstream','estimate')",
        parameters,
    ):
        groups = [total]
        if row["model"] in models:
            groups.append(by_model.setdefault(row["model"], ({}, {})))
        if daily_start is not None and row["day"] >= daily_start:
            groups.append(by_day.setdefault(row["day"], ({}, {})))
        for group in groups:
            add_row_charges(group, row)

    def view(group):
        return {"charges": charge_list(group[0]), "estimatedCharges": charge_list(group[1])}

    return {
        "total": view(total),
        "models": {key: view(value) for key, value in by_model.items()},
        "daily": {key: view(value) for key, value in by_day.items()},
    }


def usage_statistics(db, day, days):
    if type(days) is not int or not 0 <= days <= 90:
        raise DomainError("INVALID_MODEL_USAGE_RANGE")
    end = date.fromisoformat(day)
    start = (end - timedelta(days=min(days - 1, end.toordinal() - 1))).isoformat() if days else None
    where, parameters = "day<=?", [day]
    if start:
        where += " AND day>=?"
        parameters.append(start)
    total = db.execute(
        f"SELECT {USAGE_COLUMNS},MIN(day) AS first_day FROM model_proxy_calls WHERE {where}",
        parameters,
    ).fetchone()
    start = start or total["first_day"] or day
    daily_start = max(start, (end - timedelta(days=min(89, end.toordinal() - 1))).isoformat())
    daily_rows = db.execute(
        f"SELECT day,{USAGE_COLUMNS} FROM model_proxy_calls WHERE day>=? AND day<=? GROUP BY day ORDER BY day",
        (daily_start, day),
    ).fetchall()
    models = db.execute(
        f"SELECT model,{USAGE_COLUMNS} FROM model_proxy_calls WHERE {where} GROUP BY model ORDER BY requests DESC,model LIMIT 201",
        parameters,
    ).fetchall()
    costs = money_records(
        db,
        where,
        parameters,
        models={row["model"] for row in models[:200]},
        daily_start=daily_start,
    )
    no_cost = {"charges": [], "estimatedCharges": []}
    indexed = {
        row["day"]: {**usage_totals(row), **costs["daily"].get(row["day"], no_cost)}
        for row in daily_rows
    }
    empty = {**{key: 0 for key in usage_totals(total)}, **no_cost}
    daily, current = [], date.fromisoformat(daily_start)
    while current <= end:
        name = current.isoformat()
        daily.append({"day": name, **indexed.get(name, empty)})
        current += timedelta(days=1)
    return {
        "days": days,
        "startDay": start,
        "endDay": day,
        "dailyStartDay": daily_start,
        "total": {**usage_totals(total), **costs["total"]},
        "daily": daily,
        "hourly": hourly_statistics(db, day, usage_totals(total)) if days == 1 else [],
        "models": [
            {
                "model": row["model"],
                **usage_totals(row),
                **costs["models"].get(row["model"], no_cost),
            }
            for row in models[:200]
        ],
        "modelsTruncated": len(models) > 200,
    }
