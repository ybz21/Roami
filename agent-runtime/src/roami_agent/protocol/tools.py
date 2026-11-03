from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from roami_agent.protocol.tool_arguments import ToolArgumentsError, validate_tool_arguments


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict, dict], Awaitable[object]]
    effect: str = "read"
    main: bool = False
    cancellation_stops_execution: bool = False
    source: str = "builtin"
    model_schema: dict | None = None

    def validate(self, arguments):
        if self.model_schema is not None and isinstance(arguments, dict):
            legacy_fields = (
                self.schema.get("properties", {}).keys()
                - self.model_schema.get("properties", {}).keys()
            )
            if legacy_fields & arguments.keys():
                validate_tool_arguments(self.schema, arguments)
                return
        try:
            validate_tool_arguments(self.model_schema or self.schema, arguments)
        except ToolArgumentsError:
            if self.model_schema is not None:
                try:
                    validate_tool_arguments(self.schema, arguments)
                    return
                except ToolArgumentsError:
                    pass
            raise

    def wire(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.model_schema or self.schema,
            },
        }


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }
