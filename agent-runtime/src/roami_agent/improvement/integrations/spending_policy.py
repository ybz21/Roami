"""One spending policy for explicit runtime bindings and inherited model contexts."""

MODEL_ADMISSION_BLOCKERS = (
    "MODEL_PROXY_USAGE_UNKNOWN",
    "MODEL_PROXY_CURRENCY_MISMATCH",
    "MODEL_PROXY_DAILY_LIMIT",
)


def uses_shared_model_limit(ledger=None):
    from roami_agent.providers.model_proxy import model_proxy_context

    return getattr(ledger, "shared_daily_limit", False) or model_proxy_context.get() is not None


def model_proxy_for(service):
    from roami_agent.providers.model_proxy import model_proxy_context

    return getattr(service, "model_proxy", None) or model_proxy_context.get()
