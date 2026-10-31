"""Inspect CSV snapshots and publish a cleaned source-schema projection."""

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from export_spec import load_spec
from numeric_representation import integral_decimal_fields
from table_publication import PublicationError, Workspace


def table(workspace, path, expected=None):
    body = workspace.read(path)
    sha = hashlib.sha256(body).hexdigest()
    if expected is not None and sha != expected:
        raise PublicationError("SOURCE_CHANGED")
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig")), strict=True))
    if not rows or not rows[0] or len(set(rows[0])) != len(rows[0]):
        raise PublicationError("TABLE_COLUMNS_INVALID")
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise PublicationError("TABLE_ROW_WIDTH_INVALID")
    return rows[0], rows[1:], sha


def inspect(workspace, path):
    columns, rows, sha = table(workspace, path)
    return {
        "path": path,
        "sha256": sha,
        "columns": columns,
        "rows": len(rows),
        "integralDecimalFields": integral_decimal_fields(columns, rows),
    }


def key_value(values, keys, date_keys):
    result = []
    for field in keys:
        value = values[field]
        if field in date_keys:
            try:
                value = datetime.fromisoformat(value).date().isoformat()
            except ValueError:
                raise PublicationError("TABLE_DATE_KEY_INVALID") from None
        result.append(value)
    return tuple(result)


def export(
    workspace,
    source,
    analysis,
    destination,
    source_sha,
    analysis_sha,
    *,
    keys=(),
    date_keys=(),
    numeric=(),
    value_mode="analysis",
    analysis_key_values=False,
    columns=None,
    expected_destination=None,
):
    original, raw, _ = table(workspace, source, source_sha)
    available, selected, _ = table(workspace, analysis, analysis_sha)
    wanted = original if columns is None else columns
    if not wanted or len(set(wanted)) != len(wanted):
        raise PublicationError("TABLE_COLUMNS_INVALID")
    if (
        len(set(keys)) != len(keys)
        or not set(numeric) <= set(wanted)
        or not set(date_keys) <= set(keys)
    ):
        raise PublicationError(
            "TABLE_FIELD_SELECTION_INVALID",
            details={
                "invalidNumericFields": sorted(set(numeric) - set(wanted)),
                "invalidDateKeys": sorted(set(date_keys) - set(keys)),
                "availableColumns": wanted,
                "recovery": "Keep complete field names as argv items or arrays in --spec; correct the selection without dropping intended fields.",
            },
        )
    if value_mode not in {"source", "analysis"}:
        raise PublicationError("TABLE_VALUE_MODE_INVALID")
    missing = set(wanted) - set(available)
    if not missing <= set(original):
        raise PublicationError("TABLE_COLUMNS_MISSING")
    lookup = {}
    recovery = bool(missing) or value_mode == "source" or bool(keys)
    if recovery:
        if not keys or not set(keys) <= set(original) & set(available):
            raise PublicationError("TABLE_SOURCE_KEYS_REQUIRED")
        requested = {
            key_value(dict(zip(available, row)), keys, date_keys) for row in selected
        }
        for row in raw:
            try:
                key = key_value(dict(zip(original, row)), keys, date_keys)
            except PublicationError:
                continue
            if key not in requested:
                continue
            if key in lookup:
                raise PublicationError("TABLE_SOURCE_KEYS_AMBIGUOUS")
            lookup[key] = dict(zip(original, row))
        if set(lookup) != requested:
            raise PublicationError("TABLE_SOURCE_KEYS_UNMATCHED")
    projected = []
    for row in selected:
        values = dict(zip(available, row))
        if recovery:
            original_values = lookup[key_value(values, keys, date_keys)]
            values = (
                {**values, **original_values}
                if value_mode == "source"
                else {**original_values, **values}
            )
            if not analysis_key_values:
                values.update({field: original_values[field] for field in date_keys})
        output = []
        for field in wanted:
            value = values[field]
            if field in numeric and value:
                try:
                    number = Decimal(value)
                except InvalidOperation:
                    raise PublicationError("TABLE_NUMERIC_VALUE_INVALID") from None
                if not number.is_finite():
                    raise PublicationError("TABLE_NUMERIC_VALUE_INVALID")
                if number == number.to_integral_value() and "e" not in value.lower():
                    integer = (
                        value.strip().lstrip("+-").split(".", 1)[0].lstrip("0") or "0"
                    )
                    value = ("-" if number.is_signed() and number else "") + integer
            output.append(value)
        projected.append(output)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(wanted)
    writer.writerows(projected)
    body = buffer.getvalue().encode()
    if list(csv.reader(io.StringIO(body.decode()), strict=True)) != [
        wanted,
        *projected,
    ]:
        raise PublicationError("TABLE_ROUNDTRIP_FAILED")
    receipt = workspace.publish(
        {source: source_sha, analysis: analysis_sha},
        destination,
        expected_destination,
        body,
    )
    return {
        **receipt,
        "columns": wanted,
        "rows": len(projected),
        "excludedAnalysisColumns": [name for name in available if name not in wanted],
        "recoveredSourceColumns": [name for name in wanted if name in missing],
        "valueMode": value_mode,
        "numericFields": [field for field in wanted if field in numeric],
        "retainedIntegralDecimalFields": integral_decimal_fields(
            wanted, projected, exclude=numeric
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "export"])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--path")
    parser.add_argument("--source")
    parser.add_argument("--analysis")
    parser.add_argument("--destination")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-analysis-sha256")
    parser.add_argument("--expected-destination-sha256")
    parser.add_argument("--values", choices=["analysis", "source"])
    parser.add_argument("--analysis-key-values", action="store_true")
    parser.add_argument("--keys", nargs="+", default=[])
    parser.add_argument("--date-keys", nargs="+", default=[])
    parser.add_argument("--numeric", nargs="+", default=[])
    parser.add_argument("--columns", nargs="+")
    args = parser.parse_args(argv)
    export_options = (
        args.source,
        args.analysis,
        args.destination,
        args.expected_source_sha256,
        args.expected_analysis_sha256,
        args.expected_destination_sha256,
        args.values,
        args.analysis_key_values,
        args.keys,
        args.date_keys,
        args.numeric,
        args.columns,
    )
    if args.operation == "inspect" and (
        not args.path or args.spec or any(export_options)
    ):
        parser.error("inspect requires only --path and --workspace")
    if args.spec and any(export_options):
        parser.error("--spec cannot be combined with individual export options")
    if args.operation == "export" and (
        args.path or not args.spec and not all(export_options[:5])
    ):
        parser.error(
            "export requires source, analysis, destination and both observed hashes"
        )
    try:
        workspace = Workspace(args.workspace)
        if args.operation == "inspect":
            result = inspect(workspace, args.path)
        elif args.spec:
            specification, spec_sha = load_spec(workspace, args.spec)
            if workspace.relative(args.spec) == workspace.relative(
                specification["destination"]
            ):
                raise PublicationError("OUTPUT_MUST_DIFFER")
            result = export(workspace, **specification)
            result["specSha256"] = spec_sha
        else:
            result = export(
                workspace,
                args.source,
                args.analysis,
                args.destination,
                args.expected_source_sha256,
                args.expected_analysis_sha256,
                keys=args.keys,
                date_keys=args.date_keys,
                numeric=args.numeric,
                value_mode=args.values or "analysis",
                analysis_key_values=args.analysis_key_values,
                columns=args.columns,
                expected_destination=args.expected_destination_sha256,
            )
        print(json.dumps({"ok": True, **result}))
        return 0
    except (PublicationError, OSError, UnicodeError, csv.Error) as error:
        code = (
            str(error)
            if isinstance(error, PublicationError)
            else "TABLE_INPUT_UNAVAILABLE"
        )
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": code,
                    "writePublished": getattr(error, "published", False),
                    **(
                        {"details": error.details}
                        if isinstance(error, PublicationError) and error.details
                        else {}
                    ),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
