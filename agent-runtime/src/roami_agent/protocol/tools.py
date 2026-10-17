from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict, dict], Awaitable[object]]
    effect: str = "read"
    main: bool = False
    cancellation_stops_execution: bool = False

    def wire(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }
