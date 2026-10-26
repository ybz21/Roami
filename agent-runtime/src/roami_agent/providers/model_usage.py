"""Bounded daily and per-model views of the immutable local charge ledger."""

from datetime import date, timedelta

from roami_agent.protocol.errors import DomainError

USAGE_COLUMNS = """
COUNT(*) AS requests,
COALESCE(SUM(cost_nano),0) AS cost,
COALESCE(SUM(state='unknown'),0) AS unknown,
COALESCE(SUM(state='pending'),0) AS pending,
COALESCE(SUM(state='failed'),0) AS failed,
COALESCE(SUM(state='unknown' AND prices_json IS NULL),0) AS unpriced,
COALESCE(SUM(state='unknown' AND (input_tokens IS NULL OR output_tokens IS NULL)),0) AS missing_usage,
COALESCE(SUM(input_tokens),0) AS input,
COALESCE(SUM(output_tokens),0) AS output,
COALESCE(SUM(cache_read_tokens),0) AS cache
"""


def usage_totals(row):
    return {
        "requests": row["requests"],
        "knownCost": row["cost"] / 1_000_000_000,
        "unknown": row["unknown"],
        "pending": row["pending"],
        "failed": row["failed"],
        "unpriced": row["unpriced"],
        "missingUsage": row["missing_usage"],
        "inputTokens": row["input"],
        "outputTokens": row["output"],
        "cacheReadTokens": row["cache"],
        "totalTokens": row["input"] + row["output"],
    }


def usage_statistics(db, day, days):
    if type(days) is not int or not 0 <= days <= 90:
        raise DomainError("INVALID_MODEL_USAGE_RANGE")
    end = date.fromisoformat(day)
    start = (end - timedelta(days=days - 1)).isoformat() if days else None
    where, parameters = "day<=?", [day]
    if start:
        where += " AND day>=?"
        parameters.append(start)
    total = db.execute(
        f"SELECT {USAGE_COLUMNS},MIN(day) AS first_day FROM model_proxy_calls WHERE {where}",
        parameters,
    ).fetchone()
    start = start or total["first_day"] or day
    daily_start = max(start, (end - timedelta(days=89)).isoformat())
    daily_rows = db.execute(
        f"SELECT day,{USAGE_COLUMNS} FROM model_proxy_calls WHERE day>=? AND day<=? GROUP BY day ORDER BY day",
        (daily_start, day),
    ).fetchall()
    indexed = {row["day"]: usage_totals(row) for row in daily_rows}
    empty = {key: 0 for key in usage_totals(total)}
    daily = []
    current = date.fromisoformat(daily_start)
    while current <= end:
        name = current.isoformat()
        daily.append({"day": name, **indexed.get(name, empty)})
        current += timedelta(days=1)
    models = db.execute(
        f"SELECT model,{USAGE_COLUMNS} FROM model_proxy_calls WHERE {where} GROUP BY model ORDER BY cost DESC,model LIMIT 201",
        parameters,
    ).fetchall()
    return {
        "days": days,
        "startDay": start,
        "endDay": day,
        "dailyStartDay": daily_start,
        "total": usage_totals(total),
        "daily": daily,
        "models": [{"model": row["model"], **usage_totals(row)} for row in models[:200]],
        "modelsTruncated": len(models) > 200,
    }
