"""Compare explicitly chosen CSV statistics with immutable source receipts."""

import argparse
import csv
import hashlib
import json
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    Underflow,
    localcontext,
)
from statistics import mean

from csv_export import table
from table_publication import PublicationError, Workspace

STATISTICS = ("mean", "median", "minimum", "maximum", "first", "last")


def statistic(values, name):
    if name == "mean":
        return mean(values)
    if name == "median":
        ordered = sorted(values)
        middle = len(ordered) // 2
        return (
            ordered[middle]
            if len(ordered) % 2
            else mean(ordered[middle - 1 : middle + 1])
        )
    return {
        "minimum": min,
        "maximum": max,
        "first": lambda v: v[0],
        "last": lambda v: v[-1],
    }[name](values)


def observe(workspace, path, selected, name, expected):
    try:
        columns, rows, sha = table(workspace, path, expected)
    except csv.Error:
        raise PublicationError("TABLE_CSV_INVALID") from None
    if (
        not selected
        or len(set(selected)) != len(selected)
        or not set(selected) <= set(columns)
    ):
        raise PublicationError(
            "TABLE_FIELD_SELECTION_INVALID", details={"availableColumns": columns}
        )
    output = {}
    for column in selected:
        values, missing = [], 0
        index = columns.index(column)
        for number, row in enumerate(rows, 2):
            cell = row[index].strip()
            if not cell:
                missing += 1
                continue
            try:
                value = Decimal(cell)
            except DecimalException:
                value = Decimal("NaN")
            if not value.is_finite():
                raise PublicationError(
                    "TABLE_NUMERIC_VALUE_INVALID",
                    details={"column": column, "row": number},
                )
            values.append(value)
        if not values:
            raise PublicationError("TABLE_COMPARISON_EMPTY", details={"column": column})
        output[column] = {
            "value": statistic(values, name),
            "observations": len(values),
            "sourceMissingCells": missing,
        }
    return {"path": path, "sha256": sha, "rows": len(rows)}, output


def compare(
    workspace,
    baseline,
    current,
    selected,
    name,
    expected_baseline=None,
    expected_current=None,
):
    if name not in STATISTICS:
        raise PublicationError("TABLE_STATISTIC_INVALID")
    context = Context(prec=50, rounding=ROUND_HALF_EVEN)
    context.traps[Underflow] = True
    try:
        with localcontext(context):
            before, first = observe(
                workspace, baseline, selected, name, expected_baseline
            )
            after, last = observe(workspace, current, selected, name, expected_current)
            comparisons = {}
            for column in selected:
                a, b = first[column]["value"], last[column]["value"]
                difference = b - a
                fraction = difference / a if a else None
                comparisons[column] = {
                    "baseline": {**first[column], "value": str(a)},
                    "current": {**last[column], "value": str(b)},
                    "difference": str(difference),
                    "fractionalChange": str(fraction) if fraction is not None else None,
                    "percentageDisplay": format(fraction * 100, ".1f") + "%"
                    if fraction is not None
                    else None,
                    "percentageUnavailable": "zero_baseline" if not a else None,
                    "direction": "increase"
                    if b > a
                    else "decrease"
                    if b < a
                    else "unchanged",
                }
    except DecimalException:
        raise PublicationError("TABLE_COMPARISON_RANGE") from None
    if any(
        hashlib.sha256(workspace.read(source["path"])).hexdigest() != source["sha256"]
        for source in (before, after)
    ):
        raise PublicationError("SOURCE_CHANGED")
    return {
        "baselineSource": before,
        "currentSource": after,
        "statistic": name,
        "conventions": {
            "numericEncoding": "decimal strings; 50 significant digits, round-half-even arithmetic",
            "difference": "current statistic - baseline statistic",
            "fractionalChange": "current statistic / baseline statistic - 1; signed baseline; null at zero",
            "percentageDisplay": "100 * fractionalChange; one decimal place, round-half-even",
            "direction": "current statistic compared numerically with baseline; a negative baseline can reverse the fractional-change sign",
            "missing": "empty cells omitted separately; observation counts remain explicit",
        },
        "comparisons": comparisons,
        "sourceChanged": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--columns", nargs="+", required=True)
    parser.add_argument("--statistic", choices=STATISTICS, required=True)
    parser.add_argument("--expected-baseline-sha256")
    parser.add_argument("--expected-current-sha256")
    args = parser.parse_args()
    try:
        result = compare(
            Workspace(args.workspace),
            args.baseline,
            args.current,
            args.columns,
            args.statistic,
            args.expected_baseline_sha256,
            args.expected_current_sha256,
        )
    except (PublicationError, OSError, UnicodeError, ValueError) as error:
        result = {"error": str(error), "writePublished": False}
        if isinstance(error, PublicationError) and error.details:
            result["details"] = error.details
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
