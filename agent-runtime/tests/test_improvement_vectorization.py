import asyncio
import time

import pytest

from roami_agent.improvement.containers import ContainerExecutor
from roami_agent.improvement.vectorization import grade_vectorization, skeleton
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings

SOURCE = "import math\nclass Conv2DLayer:\n def forward(self,x):\n  return x\n"


def test_only_forward_body_can_change():
    assert skeleton(SOURCE) == skeleton(SOURCE.replace("return x", "return x+1"))
    assert skeleton(SOURCE) != skeleton(SOURCE.replace("import math", "import os"))
    assert skeleton(SOURCE) != skeleton(SOURCE.replace("self,x", "self,x,y"))
    with pytest.raises(DomainError, match="FORWARD_CONTRACT_REQUIRED"):
        skeleton("pass")


async def test_unmodified_source_and_untrusted_submitted_time_cannot_pass(tmp_path):
    (tmp_path / "train.py").write_text(SOURCE)
    (tmp_path / "submission.csv").write_text("0.000001\n")

    class Forbidden:
        async def sandbox(self, *args, **kwargs):
            raise AssertionError("Unchanged source should fail before performance runs")

    grade = await grade_vectorization(
        {"judge": {"source": SOURCE, "max_time_ratio": 0.9}}, tmp_path, Forbidden()
    )
    assert not grade["passed"] and not grade["checks"]["actual_change"]


async def test_artifact_verification_is_inside_total_delivery_deadline(tmp_path, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(0.1)
        return {"passed": True}

    monkeypatch.setattr("roami_agent.improvement.code_contract.grade_code_contract", slow)
    executor = ContainerExecutor(Settings())
    case = {"limits": {"seconds": 1}, "judge": {"kind": "python_contract"}}
    with pytest.raises(TimeoutError):
        await executor.verify(case, tmp_path, "", started=time.monotonic() - 0.99)
