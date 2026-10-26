"""Validated model rates and exact fallback charges for completed token usage."""

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext

from roami_agent.protocol.errors import DomainError


def amount(value):
    if type(value) not in {int, float}:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= 1_000_000 or number.as_tuple().exponent < -6:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    return number


def currency_value(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    return value


def model_prices(raw, currency):
    if not isinstance(raw, dict) or len(raw) > 32:
        raise DomainError("INVALID_MODEL_PROXY_CONFIG")
    result = {}
    for model, rate in raw.items():
        if (
            not isinstance(model, str)
            or not model
            or model.strip() != model
            or len(model) > 200
            or not isinstance(rate, dict)
            or set(rate) - {"currency", "input", "output", "cacheRead"}
        ):
            raise DomainError("INVALID_MODEL_PROXY_CONFIG")
        amount(rate.get("input"))
        amount(rate.get("output"))
        if rate.get("cacheRead") is not None:
            amount(rate["cacheRead"])
        result[model] = {
            "currency": currency_value(rate.get("currency", currency)),
            "input": rate["input"],
            "output": rate["output"],
            "cacheRead": rate.get("cacheRead"),
        }
    return result


@dataclass(frozen=True)
class ConfiguredCharge:
    amount: Decimal
    currency: str


def local_charge(rate, counts):
    input_tokens, output_tokens, cached_tokens = counts
    cached_rate = rate["input"] if rate["cacheRead"] is None else rate["cacheRead"]
    with localcontext() as context:
        context.prec = 50
        total = (
            (input_tokens - cached_tokens) * Decimal(str(rate["input"]))
            + output_tokens * Decimal(str(rate["output"]))
            + cached_tokens * Decimal(str(cached_rate))
        ) / 1_000_000
    return ConfiguredCharge(total, rate["currency"])
