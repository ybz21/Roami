import asyncio
import re


class DomainError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


class TaskVerificationRecorded(DomainError):
    def __init__(self, verification):
        self.verification = verification
        super().__init__("TASK_NOT_WAITING_VERIFICATION", 409)


class ProjectReviewInputError(DomainError):
    def __init__(self):
        super().__init__("OKR_REVIEW_INPUT_INVALID", 400)


class ModelAdmissionRejected(DomainError):
    """The trusted model transport rejected admission before sending a request."""


class FreeModelAdmissionDeferred(ModelAdmissionRejected):
    """The private gateway rejected a free request before contacting an upstream."""

    def __init__(self, retry_at_ms):
        self.retry_at_ms = retry_at_ms
        super().__init__("MODEL_ROUTE_NO_AVAILABLE_MEMBER", 503)


class ToolPreflightError(DomainError):
    """An unavailable dependency prevents starting the tool action."""


class ToolFinalizationRequired(ToolPreflightError):
    """An unchanged blocker allows reporting existing evidence, but no further tools."""


class ToolCancellation(asyncio.CancelledError):
    def __init__(self, *, input_stopped):
        super().__init__()
        self.input_stopped = input_stopped is True


def public_error_code(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", value) else None
    )
