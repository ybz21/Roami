"""Schema-only diagnostics for correcting tool calls without echoing supplied values."""

from itertools import islice

from jsonschema import Draft202012Validator

from roami_agent.protocol.errors import DomainError


class ToolArgumentsError(DomainError):
    def __init__(self, issues, truncated):
        super().__init__("INVALID_TOOL_ARGUMENTS")
        self.issues, self.truncated = issues, truncated


def validate_tool_arguments(schema, arguments):
    errors = list(islice(Draft202012Validator(schema).iter_errors(arguments), 13))
    if not errors:
        return
    issues = []
    for error in errors[:12]:
        issue = {"path": list(error.absolute_path), "rule": error.validator}
        if error.validator == "required" and isinstance(error.instance, dict):
            issue["missingFields"] = [
                key for key in error.validator_value if key not in error.instance
            ]
        elif error.validator == "additionalProperties":
            issue["allowedFields"] = list(error.schema.get("properties", {}))
        elif error.validator in {"type", "enum", "minLength", "maxLength", "minimum", "maximum"}:
            issue["expected"] = error.validator_value
        issues.append(issue)
    raise ToolArgumentsError(issues, len(errors) > 12) from errors[0]
