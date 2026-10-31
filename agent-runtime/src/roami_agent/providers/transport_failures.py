"""Stable transport categories without exception text or private connection details."""

import httpx


def transport_failure(error, response_started):
    response_stage = "response_body" if response_started else "response_headers"
    categories = (
        (httpx.ConnectTimeout, "connect_timeout", "connect"),
        (httpx.ConnectError, "connect_error", "connect"),
        (httpx.ReadTimeout, "read_timeout", response_stage),
        (httpx.ReadError, "read_error", response_stage),
        (httpx.RemoteProtocolError, "protocol_error", response_stage),
        (httpx.WriteTimeout, "write_timeout", "request_body"),
        (httpx.WriteError, "write_error", "request_body"),
        (httpx.PoolTimeout, "pool_timeout", "connection_pool"),
    )
    for kind, name, stage in categories:
        if isinstance(error, kind):
            return {"failureType": name, "failureStage": stage}
    return {"failureType": "transport_error", "failureStage": "transport"}


def transport_receipt(value):
    if not isinstance(value, dict):
        return None
    allowed_stages = {
        "connect_error": {"connect"},
        "connect_timeout": {"connect"},
        "read_error": {"response_headers", "response_body"},
        "read_timeout": {"response_headers", "response_body"},
        "protocol_error": {"response_headers", "response_body"},
        "write_error": {"request_body"},
        "write_timeout": {"request_body"},
        "pool_timeout": {"connection_pool"},
        "transport_error": {"transport"},
    }
    kind, stage = value.get("failureType"), value.get("failureStage")
    if (
        value.get("phase") not in ("retry", "transport_error")
        or type(value.get("attempt")) is not int
        or value["attempt"] < 1
        or value.get("errorCode") not in ("MODEL_TRANSPORT_FAILED", "MODEL_RETRY_DEADLINE")
        or not isinstance(kind, str)
        or not isinstance(stage, str)
        or stage not in allowed_stages.get(kind, set())
    ):
        return None
    return {
        key: value[key] for key in ("phase", "attempt", "errorCode", "failureType", "failureStage")
    }


def relayed_transport_failure(value, attempt):
    receipt = transport_receipt(value)
    if receipt is None:
        return None
    return {
        **receipt,
        "phase": "upstream_" + receipt["phase"],
        "upstreamAttempt": receipt["attempt"],
        "attempt": attempt,
    }
