"""Read-only CSV distribution metrics with source hashes and named conventions."""

import argparse
import hashlib
import json
import math

from csv_export import table
from distribution_moments import moments
from table_publication import PublicationError, Workspace


def profile(workspace, path, selected, transform="values", expected=None):
    columns, rows, sha = table(workspace, path, expected)
    if (
        not selected
        or len(set(selected)) != len(selected)
        or not set(selected) <= set(columns)
    ):
        raise PublicationError(
            "TABLE_FIELD_SELECTION_INVALID", details={"availableColumns": columns}
        )
    if transform not in {"values", "fractional_change"}:
        raise PublicationError("TABLE_TRANSFORM_INVALID")
    output = {}
    for column in selected:
        index, previous, missing = columns.index(column), None, 0
        values = []
        for row_number, row in enumerate(rows, 2):
            cell = row[index].strip()
            if not cell:
                missing += 1
                previous = None
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
            if transform == "values":
                values.append(value)
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
            previous = value
        output[column] = {**moments(values), "sourceMissingCells": missing}
    if hashlib.sha256(workspace.read(path)).hexdigest() != sha:
        raise PublicationError("SOURCE_CHANGED")
    return {
        "source": {"path": path, "sha256": sha, "rows": len(rows), "columns": columns},
        "transform": transform,
        "order": "input row order; missing cells break fractional-change sequences",
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
    args = parser.parse_args()
    try:
        result = profile(
            Workspace(args.workspace),
            args.path,
            args.columns,
            args.transform,
            args.expected_sha256,
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
