"""Keep bounded container stderr in private Case evidence, outside public error codes."""

import copy
from contextvars import ContextVar
from functools import wraps

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.native_public_record import public_value

_failures = ContextVar("rsi_container_failures", default=None)
MAX_FAILURES = 4
STDERR_BYTES = 2048


class ContainerCommandFailure(DomainError):
    def __init__(self, operation, exit_code, stderr):
        super().__init__("RSI_DOCKER_COMMAND_FAILED")
        text = public_value(stderr.decode("utf-8", errors="replace"))
        encoded = text.encode("utf-8")
        self.diagnostic = {
            "operation": operation
            if operation in {"create", "start", "image", "inspect", "rm", "exec", "logs", "wait"}
            else "command",
            "exit_code": exit_code,
            "stderr": encoded[-STDERR_BYTES:].decode("utf-8", errors="ignore"),
            "stderr_truncated": len(encoded) > STDERR_BYTES,
        }
        # Native graders can catch a failure before it reaches the run boundary.
        if current := _failures.get():
            current["total"] += 1
            if len(current["failures"]) < MAX_FAILURES:
                current["failures"].append(self.diagnostic)


def _snapshot(current):
    return {
        "source": "host_container_command",
        "failures": copy.deepcopy(current["failures"]),
        "omitted_failures": current["total"] - len(current["failures"]),
    }


def failure_fields(value):
    evidence = (
        value.get("execution_diagnostics")
        if isinstance(value, dict)
        else getattr(value, "execution_diagnostics", None)
    )
    if evidence:
        return {"execution_diagnostics": copy.deepcopy(evidence)}
    if isinstance(value, ContainerCommandFailure):
        return {"execution_diagnostics": _snapshot({"failures": [value.diagnostic], "total": 1})}
    return {}


def capture_failures(run):
    @wraps(run)
    async def captured(*args, **kwargs):
        current = {"failures": [], "total": 0}
        token = _failures.set(current)
        try:
            result = await run(*args, **kwargs)
            result.pop("execution_diagnostics", None)
            if current["total"]:
                result["execution_diagnostics"] = _snapshot(current)
            return result
        except BaseException as error:
            if current["total"]:
                error.execution_diagnostics = _snapshot(current)
            raise
        finally:
            _failures.reset(token)

    return captured
