"""Read CSV export arguments as data, preserving field-name boundaries."""

import hashlib
import json
import re

from table_publication import PublicationError

REQUIRED = {
    "source": "source",
    "analysis": "analysis",
    "destination": "destination",
    "expectedSourceSha256": "source_sha",
    "expectedAnalysisSha256": "analysis_sha",
    "numeric": "numeric",
}
OPTIONAL = {
    "expectedDestinationSha256": "expected_destination",
    "keys": "keys",
    "dateKeys": "date_keys",
    "columns": "columns",
    "values": "value_mode",
    "analysisKeyValues": "analysis_key_values",
    "preserveNumericText": "preserve_numeric_text",
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PublicationError("TABLE_SPEC_DUPLICATE_FIELD", details={"field": key})
        result[key] = value
    return result


def load_spec(workspace, path):
    body = workspace.read(path)
    try:
        value = json.loads(body.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        if isinstance(error, PublicationError):
            raise
        raise PublicationError("TABLE_SPEC_INVALID_JSON") from None
    if not isinstance(value, dict):
        raise PublicationError("TABLE_SPEC_OBJECT_REQUIRED")
    missing = sorted(REQUIRED.keys() - value.keys())
    unknown = sorted(value.keys() - REQUIRED.keys() - OPTIONAL.keys())
    if missing or unknown:
        raise PublicationError(
            "TABLE_SPEC_FIELDS_INVALID",
            details={"missing": missing, "unknown": unknown},
        )
    invalid = []
    for name in {**REQUIRED, **OPTIONAL}:
        if name not in value:
            continue
        item = value[name]
        if name in {"keys", "dateKeys", "numeric", "columns", "preserveNumericText"}:
            valid = isinstance(item, list) and all(
                isinstance(part, str) and "\0" not in part for part in item
            )
        elif name == "analysisKeyValues":
            valid = type(item) is bool
        elif name == "values":
            valid = item in ["source", "analysis"]
        elif "Sha256" in name:
            valid = isinstance(item, str) and bool(re.fullmatch(r"[a-f0-9]{64}", item))
            if name == "expectedDestinationSha256" and item is None:
                valid = True
        else:
            valid = isinstance(item, str) and bool(item) and "\0" not in item
        if not valid:
            invalid.append(name)
    if invalid:
        raise PublicationError("TABLE_SPEC_VALUES_INVALID", details={"fields": invalid})
    return (
        {
            field: value[name]
            for name, field in {**REQUIRED, **OPTIONAL}.items()
            if name in value
        },
        hashlib.sha256(body).hexdigest(),
    )
