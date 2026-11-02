"""Descriptive facts with one shared row order and explicit observation cohorts."""

import csv
import io
import math

import pandas as pd


def finite(value):
    return float(value) if pd.notna(value) and math.isfinite(float(value)) else None


def day(value):
    return value.date().isoformat()


def csv_header(body):
    try:
        header = next(csv.reader(io.StringIO(body.decode("utf-8-sig")), strict=True))
    except (csv.Error, StopIteration):
        raise ValueError("CSV_HEADER_REQUIRED") from None
    if not header or len(header) != len(set(header)):
        raise ValueError("UNIQUE_CSV_HEADER_REQUIRED")
    return header


def analyze(body, args):
    try:
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig")), strict=True))
    except csv.Error:
        raise ValueError("INVALID_CSV") from None
    if (
        not rows
        or len(rows[0]) != len(set(rows[0]))
        or any(row and len(row) != len(rows[0]) for row in rows[1:])
    ):
        raise ValueError("UNIQUE_HEADER_AND_RECTANGULAR_CSV_REQUIRED")
    source = pd.read_csv(io.BytesIO(body))
    if len({args.date, args.price, args.volume}) != 3:
        raise ValueError("DISTINCT_DATE_PRICE_VOLUME_REQUIRED")
    columns = list(dict.fromkeys([args.price, args.volume, *args.matrix]))
    if args.date not in source or any(name not in source for name in columns):
        raise ValueError("COLUMN_NOT_FOUND")
    if not all(isinstance(value, str) for value in source[args.date]):
        raise ValueError("EXPLICIT_DATE_STRINGS_REQUIRED")
    stamps = [pd.Timestamp(value) for value in source[args.date]]
    if any(pd.isna(stamp) for stamp in stamps):
        raise ValueError("DAILY_UNIQUE_DATES_REQUIRED")
    dates = pd.DatetimeIndex(
        [
            stamp.tz_localize(args.calendar_timezone)
            if stamp.tzinfo is None
            else stamp.tz_convert(args.calendar_timezone)
            for stamp in stamps
        ]
    )
    if dates.normalize().duplicated().any():
        raise ValueError("DAILY_UNIQUE_DATES_REQUIRED")
    data = source[columns].apply(pd.to_numeric, errors="raise")
    if any(not math.isfinite(float(v)) for v in data.to_numpy().ravel()):
        raise ValueError("FINITE_NUMBERS_REQUIRED")
    data.index = dates
    data = data.sort_index()
    if len(data) < 2 or (data[args.price] <= 0).any() or (data[args.volume] < 0).any():
        raise ValueError("POSITIVE_PRICE_NONNEGATIVE_VOLUME_REQUIRED")
    price, volume = data[args.price], data[args.volume]
    returns = price.pct_change(fill_method=None)
    short = price.rolling(args.short, min_periods=args.short).mean()
    long = price.rolling(args.long, min_periods=args.long).mean()
    crossings, previous_sign = [], 0
    for stamp, difference in (short - long).dropna().items():
        sign = 1 if difference > 0 else -1 if difference < 0 else 0
        if not sign:
            continue
        if previous_sign and sign != previous_sign:
            crossings.append(
                {"date": day(stamp), "direction": "up" if sign > 0 else "down"}
            )
        previous_sign = sign
    drawdown = price / price.cummax() - 1
    correlation = data.copy()
    derived = "Return from " + args.price
    while derived in correlation:
        derived += " (derived)"
    correlation[derived] = returns
    corr = correlation.corr(min_periods=2)
    valid = correlation.notna().astype(int)
    pair_counts = valid.T @ valid
    observed_years = list(dict.fromkeys([data.index[0].year, data.index[-1].year]))
    cohorts = []
    for year in observed_years:
        cohort = volume.loc[volume.index.year == year]
        cohorts.append(
            {
                "label": f"{year} observations",
                "year": year,
                "from": day(cohort.index[0]),
                "to": day(cohort.index[-1]),
                "rows": len(cohort),
                "statistic": "median",
                "value": finite(cohort.median()),
            }
        )
    elapsed_days = (data.index[-1].date() - data.index[0].date()).days
    elapsed_years = elapsed_days / 365.25
    ratio = float(price.iloc[-1] / price.iloc[0])
    try:
        cagr = finite(math.expm1(math.log(ratio) / elapsed_years))
    except OverflowError:
        cagr = None
    r = returns.dropna()
    absolute = r.abs()
    facts = {
        "rows": len(data),
        "from": day(data.index[0]),
        "to": day(data.index[-1]),
        "columns": {
            "date": args.date,
            "price": args.price,
            "volume": args.volume,
            "matrix": columns,
        },
        "units": {"price": args.price_unit, "volume": args.volume_unit},
        "assumptions": {
            "annualSessions": args.sessions,
            "calendarYearDays": 365.25,
            "elapsedCalendarDays": elapsed_days,
            "calendarTimezone": args.calendar_timezone,
            "naiveTimestampBasis": "interpreted in calendarTimezone",
            "returnBasis": "successive observations of the selected price column; adjustment metadata not inferred",
            "correlation": "same-row Pearson, pairwise complete observations",
        },
        "price": {
            "first": finite(price.iloc[0]),
            "last": finite(price.iloc[-1]),
            "change": ratio - 1,
            "factor": ratio,
            "cagr": cagr,
            "minimum": finite(price.min()),
            "minimumDate": day(price.idxmin()),
            "maximum": finite(price.max()),
            "maximumDate": day(price.idxmax()),
        },
        "movingAverages": {
            "shortWindow": args.short,
            "longWindow": args.long,
            "shortLast": finite(short.iloc[-1]),
            "longLast": finite(long.iloc[-1]),
            "priceVsLong": finite(price.iloc[-1] / long.iloc[-1] - 1),
            "crossings": crossings,
            "crossingBasis": "sign reversal across full-window averages; zero differences carry the previous sign",
        },
        "returns": {
            "rows": len(r),
            "from": day(r.index[0]),
            "to": day(r.index[-1]),
            "mean": finite(r.mean()),
            "std": finite(r.std(ddof=1)),
            "annualVolatility": finite(r.std(ddof=1) * math.sqrt(args.sessions)),
            "p05": finite(r.quantile(0.05)),
            "p95": finite(r.quantile(0.95)),
            "minimum": finite(r.min()),
            "minimumDate": day(r.idxmin()),
            "maximum": finite(r.max()),
            "maximumDate": day(r.idxmax()),
            "excessKurtosis": finite(r.kurt())
            if len(r) >= 4 and r.nunique() > 1
            else None,
            "absoluteLag1Correlation": finite(absolute.autocorr(1))
            if len(r) >= 3 and absolute.nunique() > 1
            else None,
        },
        "volume": {
            "median": finite(volume.median()),
            "maximum": finite(volume.max()),
            "maximumDate": day(volume.idxmax()),
            "calendarCohorts": cohorts,
        },
        "drawdown": {
            "minimum": finite(drawdown.min()),
            "date": day(drawdown.idxmin()),
            "basis": "observed price divided by its running historical peak, minus one",
        },
        "correlation": {
            "labels": list(corr.columns),
            "values": [[finite(v) for v in row] for row in corr.to_numpy()],
            "pairCounts": pair_counts.to_numpy().tolist(),
        },
    }
    return facts, {
        "data": data,
        "price": price,
        "volume": volume,
        "returns": r,
        "short": short,
        "long": long,
        "drawdown": drawdown,
    }
