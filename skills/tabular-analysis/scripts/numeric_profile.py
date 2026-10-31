"""Read-only CSV distribution metrics with source hashes and named conventions."""

import argparse
import hashlib
import json
import math

from csv_export import table
from distribution_moments import moments
from table_publication import PublicationError, Workspace


def observe_extremes(extrema, value, source, previous=None):
    point = {"value": value, **source, **({"previous": previous} if previous else {})}
    for name in ("minimum", "maximum"):
        prior = extrema[name]
        if prior is None or (
            value < prior["value"] if name == "minimum" else value > prior["value"]
        ):
            extrema[name] = {**point, "occurrences": 1}
        elif value == prior["value"]:
            prior["occurrences"] += 1


def profile(workspace, path, selected, transform="values", expected=None, *, labels=()):
    columns, rows, sha = table(workspace, path, expected)
    if (
        not selected
        or len(set(selected)) != len(selected)
        or not set(selected) <= set(columns)
        or len(set(labels)) != len(labels)
        or not set(labels) <= set(columns)
    ):
        raise PublicationError(
            "TABLE_FIELD_SELECTION_INVALID", details={"availableColumns": columns}
        )
    if transform not in {"values", "fractional_change"}:
        raise PublicationError("TABLE_TRANSFORM_INVALID")
    output = {}
    for column in selected:
        index, previous, previous_source, missing = columns.index(column), None, None, 0
        values = []
        extrema = {"minimum": None, "maximum": None}
        for row_number, row in enumerate(rows, 2):
            cell = row[index].strip()
            if not cell:
                missing += 1
                previous = None
                previous_source = None
                continue
            try:
                value = float(cell)
            except ValueError:
                raise PublicationError(
                    "TABLE_NUMERIC_VALUE_INVALID",
                    details={"column": column, "row": row_number},
                ) from None
            if not math.isfinite(value):
                raise PublicationError(
                    "TABLE_NUMERIC_VALUE_INVALID",
                    details={"column": column, "row": row_number},
                )
            source = {
                "dataRow": row_number - 1,
                "sourceValue": row[index],
                "labels": {name: row[columns.index(name)] for name in labels},
            }
            if transform == "values":
                values.append(value)
                observe_extremes(extrema, value, source)
            elif previous is not None:
                if not previous:
                    raise PublicationError(
                        "TABLE_CHANGE_ZERO_BASE",
                        details={"column": column, "row": row_number},
                    )
                change = value / previous - 1
                if not math.isfinite(change):
                    raise PublicationError(
                        "TABLE_CHANGE_RANGE",
                        details={"column": column, "row": row_number},
                    )
                values.append(change)
                observe_extremes(extrema, change, source, previous_source)
            previous = value
            previous_source = source
        output[column] = {
            **moments(values),
            "sourceMissingCells": missing,
            "extrema": extrema,
        }
    if hashlib.sha256(workspace.read(path)).hexdigest() != sha:
        raise PublicationError("SOURCE_CHANGED")
    return {
        "source": {"path": path, "sha256": sha, "rows": len(rows), "columns": columns},
        "transform": transform,
        "order": "input row order; missing cells break fractional-change sequences",
        "extremaConvention": "dataRow is 1-based excluding the header; tied extrema retain the first input record and count all occurrences; fractional changes belong to the current record with previous-record evidence",
        "labelColumns": list(labels),
        "conventions": {
            "standardDeviationSample": "sample standard deviation; ddof=1",
            "kurtosisPearsonPopulation": "m4 / m2^2; theoretical normal reference 3",
            "kurtosisExcessPopulation": "m4 / m2^2 - 3; theoretical normal reference 0",
            "kurtosisExcessUnbiased": "corrected Fisher sample excess; requires n>=4; normal reference 0",
            "fractional_change": "current / previous - 1; units are fractions, not percent",
        },
        "columns": output,
        "sourceChanged": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--columns", nargs="+", required=True)
    parser.add_argument(
        "--transform", choices=["values", "fractional_change"], default="values"
    )
    parser.add_argument("--expected-sha256")
    parser.add_argument("--labels", nargs="+", default=[])
    args = parser.parse_args()
    try:
        result = profile(
            Workspace(args.workspace),
            args.path,
            args.columns,
            args.transform,
            args.expected_sha256,
            labels=args.labels,
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
