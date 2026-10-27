"""Daily and per-model token counts, with exact fees grouped by currency and source."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.upstream_costs import add_amounts

USAGE_COLUMNS = """
COUNT(*) AS requests,
COALESCE(SUM(state!='pending' AND (cost_source='unknown' OR (cost_source='estimate' AND cost_amount IS NULL))),0) AS unknown,
COALESCE(SUM(state='pending'),0) AS pending,
COALESCE(SUM(state='failed'),0) AS failed,
COALESCE(SUM(cost_source='estimate' AND cost_amount IS NULL),0) AS estimated,
COALESCE(SUM(cost_source='estimate' AND cost_amount IS NOT NULL),0) AS local_estimated,
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
        "localEstimated": row["local_estimated"],
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
    billable, local, historical = {}, {}, {}
    if row["cost_source"] == "upstream" or (
        row["cost_source"] == "estimate" and row["cost_amount"] is not None
    ):
        billable[row["cost_currency"]] = Decimal(row["cost_amount"])
        if row["cost_source"] == "estimate":
            local[row["cost_currency"]] = Decimal(row["cost_amount"])
    elif row["cost_source"] == "estimate" and row["cost_nano"] is not None:
        historical["CNY"] = Decimal(row["cost_nano"]) / 1_000_000_000
    return {
        "charges": charge_list(billable),
        "localCharges": charge_list(local),
        "estimatedCharges": charge_list(historical),
    }


def add_row_charges(group, row):
    charges = row_charges(row)
    for amounts, key in zip(group, ("charges", "localCharges", "estimatedCharges"), strict=True):
        for charge in charges[key]:
            currency = charge["currency"]
            amounts[currency] = add_amounts(
                amounts.get(currency, Decimal(0)), Decimal(charge["amount"])
            )


def hourly_statistics(db, day, fields, chart_models):
    hours = [{"hour": hour, **dict.fromkeys(fields, 0)} for hour in range(24)]
    fees = [({}, {}, {}) for _ in hours]
    model_hours = [{} for _ in hours]
    for row in db.execute("SELECT * FROM model_proxy_calls WHERE day=?", (day,)):
        hour = datetime.fromtimestamp(row["started_ms"] / 1000, ZoneInfo(row["timezone"])).hour
        source, state = row["cost_source"], row["state"]
        counts = {
            "requests": 1,
            "unknown": int(
                state != "pending"
                and (source == "unknown" or (source == "estimate" and row["cost_amount"] is None))
            ),
            "pending": int(state == "pending"),
            "failed": int(state == "failed"),
            "estimated": int(source == "estimate" and row["cost_amount"] is None),
            "localEstimated": int(source == "estimate" and row["cost_amount"] is not None),
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
        model = row["model"] if row["model"] in chart_models else None
        part, costs = model_hours[hour].setdefault(model, (dict.fromkeys(fields, 0), ({}, {}, {})))
        for field, value in counts.items():
            part[field] += value
        add_row_charges(costs, row)
    return [
        {
            **row,
            "charges": charge_list(fee[0]),
            "localCharges": charge_list(fee[1]),
            "estimatedCharges": charge_list(fee[2]),
            "models": [
                {
                    "model": model,
                    **counts,
                    "charges": charge_list(cost[0]),
                    "localCharges": charge_list(cost[1]),
                    "estimatedCharges": charge_list(cost[2]),
                }
                for model, (counts, cost) in parts.items()
            ],
        }
        for row, fee, parts in zip(hours, fees, model_hours, strict=True)
    ]


def money_records(db, where, parameters, *, models=(), daily_start=None, chart_models=()):
    total, by_model, by_day, daily_models = ({}, {}, {}), {}, {}, {}
    for row in db.execute(
        f"SELECT model,day,cost_source,cost_amount,cost_currency,cost_nano FROM model_proxy_calls WHERE {where} AND cost_source IN ('upstream','estimate')",
        parameters,
    ):
        groups = [total]
        if row["model"] in models:
            groups.append(by_model.setdefault(row["model"], ({}, {}, {})))
        if daily_start is not None and row["day"] >= daily_start:
            groups.append(by_day.setdefault(row["day"], ({}, {}, {})))
            model = row["model"] if row["model"] in chart_models else None
            groups.append(daily_models.setdefault((row["day"], model), ({}, {}, {})))
        for group in groups:
            add_row_charges(group, row)

    def view(group):
        return {
            "charges": charge_list(group[0]),
            "localCharges": charge_list(group[1]),
            "estimatedCharges": charge_list(group[2]),
        }

    return {
        "total": view(total),
        "models": {key: view(value) for key, value in by_model.items()},
        "daily": {key: view(value) for key, value in by_day.items()},
        "dailyModels": {key: view(value) for key, value in daily_models.items()},
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
    chart_models = [row["model"] for row in models[:4]]
    costs = money_records(
        db,
        where,
        parameters,
        models={row["model"] for row in models[:200]},
        daily_start=daily_start,
        chart_models=chart_models,
    )
    no_cost = {"charges": [], "localCharges": [], "estimatedCharges": []}
    placeholders = ",".join("?" for _ in chart_models) or "NULL"
    parts = db.execute(
        f"SELECT day,CASE WHEN model IN ({placeholders}) THEN model ELSE NULL END AS series_model,{USAGE_COLUMNS} FROM model_proxy_calls WHERE day>=? AND day<=? GROUP BY day,series_model ORDER BY day,series_model",
        [*chart_models, daily_start, day],
    ).fetchall()
    daily_models = {}
    for part in parts:
        model = part["series_model"]
        daily_models.setdefault(part["day"], []).append(
            {
                "model": model,
                **usage_totals(part),
                **costs["dailyModels"].get((part["day"], model), no_cost),
            }
        )
    indexed = {
        row["day"]: {**usage_totals(row), **costs["daily"].get(row["day"], no_cost)}
        for row in daily_rows
    }
    empty = {**{key: 0 for key in usage_totals(total)}, **no_cost}
    daily, current = [], date.fromisoformat(daily_start)
    while current <= end:
        name = current.isoformat()
        daily.append(
            {"day": name, **indexed.get(name, empty), "models": daily_models.get(name, [])}
        )
        current += timedelta(days=1)
    return {
        "days": days,
        "startDay": start,
        "endDay": day,
        "dailyStartDay": daily_start,
        "total": {**usage_totals(total), **costs["total"]},
        "daily": daily,
        "hourly": hourly_statistics(db, day, usage_totals(total), chart_models)
        if days == 1
        else [],
        "seriesModels": chart_models,
        "seriesTruncated": len(models) > 4,
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
