"""Bounded comparison categories and observed shape; never reference contents."""

CATEGORIES = {
    "passed",
    "column_count",
    "columns",
    "row_count",
    "dtypes",
    "values",
    "unreadable",
    "verification_failed",
}


def csv_diagnostic(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"comparison", "rows", "columns"}
        or not isinstance(value.get("comparison"), str)
        or value["comparison"] not in CATEGORIES
    ):
        return None
    shape = [value["rows"], value["columns"]]
    if not (
        all(type(n) is int and 0 <= n <= 8_000_000 for n in shape)
        or value["comparison"] in {"unreadable", "verification_failed"}
        and shape == [None, None]
    ):
        return None
    return dict(value)
