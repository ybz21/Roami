"""One spending policy for explicit runtime bindings and inherited model contexts."""

from roami_agent.improvement.domain.admission_blocking import MODEL_ADMISSION_BLOCKERS
from roami_agent.protocol.errors import DomainError


async def check_usage_admission(result, check):
    if check is None:
        return
    try:
        await check()
    except DomainError as error:
        result["admission_error"] = (
            error.code if error.code in MODEL_ADMISSION_BLOCKERS else "RSI_USAGE_UNKNOWN"
        )
    else:
        result["shared_admission_checked"] = True


def uses_shared_model_limit(ledger=None):
    from roami_agent.providers.model_proxy import model_proxy_context

    return getattr(ledger, "shared_daily_limit", False) or model_proxy_context.get() is not None


def model_proxy_for(service):
    from roami_agent.providers.model_proxy import model_proxy_context

    return getattr(service, "model_proxy", None) or model_proxy_context.get()
