"""Read existing provider charge fields without inferring a token price or exchange rate."""

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from urllib.parse import urlsplit


@dataclass(frozen=True)
class UpstreamCharge:
    amount: Decimal
    currency: str


def upstream_charge(usage, endpoint):
    if not isinstance(usage, dict) or type(usage.get("cost")) not in {int, float, Decimal}:
        return None
    value = Decimal(str(usage["cost"]))
    if not value.is_finite() or not 0 <= value <= 1_000_000_000 or value.as_tuple().exponent < -18:
        return None
    currency = usage.get("currency")
    if urlsplit(str(endpoint)).hostname == "openrouter.ai":
        # OpenRouter usage.cost is the account charge in USD credits, not upstream_inference_cost.
        if currency is not None and currency != "USD":
            return None
        currency = "USD"
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        return None
    return UpstreamCharge(value, currency)


def add_amounts(left, right):
    # Keep all 18 fractional digits even across large ledger totals.
    with localcontext() as context:
        context.prec = 50
        return left + right
