"""Observe integral decimal text without deciding a column's semantic type."""

import re

NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
INTEGRAL_DECIMAL = re.compile(r"[+-]?(?:[0-9]+\.0*|\.0+)\Z")


def integral_decimal_fields(columns, rows, *, exclude=()):
    result = []
    for index, field in enumerate(columns):
        if field in exclude:
            continue
        values = [row[index].strip() for row in rows if row[index].strip()]
        integral = sum(bool(INTEGRAL_DECIMAL.fullmatch(value)) for value in values)
        if not integral:
            continue
        numeric = [value for value in values if NUMBER.fullmatch(value)]
        leading_zero = 0
        for value in numeric:
            integer = re.split(r"[.eE]", value.lstrip("+-"), maxsplit=1)[0]
            leading_zero += len(integer) > 1 and integer.startswith("0")
        result.append(
            {
                "field": field,
                "nonemptyCount": len(values),
                "numericCount": len(numeric),
                "integralDecimalCount": integral,
                "leadingZeroCount": leading_zero,
            }
        )
    return result
