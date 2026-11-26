"""Trusted metadata and transaction guards for conversation intake."""

from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class MessageAdmission:
    request_fields: dict
    message_fields: dict
    check_binding: Callable[[Connection], None]
