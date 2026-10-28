"""Verify fresh workspace replays and committed answers without weakening case assertions."""

import hashlib
import json
import os

import pytest

from roami_agent.improvement.evaluation.authored_grading import RERUN_ANALYSIS
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.executors import committed_answer
from roami_agent.improvement.evaluation.grading import judge_case
from roami_agent.server.configuration import Settings


def assistant(text, *, turn_id="current", **content):
    return {"role": "assistant", "turn_id": turn_id, "content": {"text": text, **content}}


@pytest.mark.parametrize(
    "messages,expected,passed",
    [
        (
            [
                assistant("0.5759312320916905"),
                assistant("0.5759\n\n[answer.txt](/artifact)", source="task"),
            ],
            "0.5759312320916905",
            True,
        ),
        ([assistant("0.1"), assistant("0.57593", source="task")], "0.1", False),
        (
            [assistant("The answer is 0.57593"), assistant("0.57593", source="task")],
            "The answer is 0.57593",
            False,
        ),
        ([assistant("0.57593"), assistant("0.1")], "0.1", False),
        ([assistant("0.57593", source="task")], "0.57593", True),
        (
            [
                assistant("Working", tool_calls=[{"id": "call"}]),
                assistant("0.57593", source="task"),
            ],
            "0.57593",
            True,
        ),
        ([assistant("0.57593", turn_id="previous"), assistant("0.1", source="task")], "0.1", False),
        (
            [assistant("0.1", turn_id="previous"), assistant("0.57593", source="task")],
            "0.57593",
            True,
        ),
        (
            [assistant("0.57593"), {"role": "user", "content": {"text": "0.1"}}, assistant("")],
            "0.57593",
            True,
        ),
    ],
)
def test_numeric_judge_uses_committed_main_answer(tmp_path, messages, expected, passed):
    answer = committed_answer(messages, turn_id="current")
    assert answer == expected
    case = {"judge": {"kind": "numeric", "expected": 0.57593, "tolerance": 0.0001}}
    assert judge_case(case, answer, tmp_path)["hard_passed"] is passed


@pytest.mark.parametrize("mode", ["absolute", "relative", "package", "no_op", "symlink"])
async def test_analysis_replay_preserves_workspace_contract_and_original(tmp_path, mode):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE to a frozen evaluation image")
    original = tmp_path / "original"
    original.mkdir()
    (original / "result.json").write_text('{"stale": true}')
    (original / "prices.json").write_text('{"answer": 42}')
    (original / "local_model").mkdir()
    (original / "local_model" / "__init__.py").write_text("ANSWER = 42\n")
    script = {
        "absolute": 'import json,pathlib\np=pathlib.Path("/workspace")\n(p/"result.json").write_text((p/"prices.json").read_text())\n',
        "relative": 'import pathlib\npathlib.Path("result.json").write_text(pathlib.Path("prices.json").read_text())\n',
        "package": 'import json,pathlib\nfrom local_model import ANSWER\npathlib.Path("result.json").write_text(json.dumps({"answer":ANSWER}))\n',
        "no_op": "pass\n",
        "symlink": 'import pathlib\nassert pathlib.Path("source-link").is_symlink()\npathlib.Path("result.json").write_text(pathlib.Path("source-link").read_text())\n',
    }[mode]
    (original / "analysis.py").write_text(script)
    (original / "source-link").symlink_to("prices.json")

    def hashes():
        return {
            str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in original.rglob("*")
            if p.is_file()
        }

    before = hashes()
    executor = ContainerExecutor(Settings(), image=image)
    raw = await executor.sandbox(original, RERUN_ANALYSIS, copy_workspace=True)
    output = json.loads(raw.decode().splitlines()[-1])
    assert output["result"] == (None if mode == "no_op" else {"answer": 42})
    assert hashes() == before
    assert not (original / "local_model" / "__pycache__").exists()
    assert (original / "source-link").is_symlink()


async def test_replay_mounts_keep_source_readonly(tmp_path, monkeypatch):
    from roami_agent.improvement.evaluation.execution import containers

    commands = []

    async def docker(*args, **kwargs):
        commands.append(args)
        return b""

    async def remove(*args):
        pass

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = ContainerExecutor(Settings())
    executor.image_id = "frozen-fixture"
    monkeypatch.setattr(executor, "remove", remove)
    await executor.sandbox(tmp_path, "pass", copy_workspace=True)
    create = commands[0]
    assert f"type=bind,src={tmp_path},dst=/replay-input,readonly" in create
    assert not any("dst=/workspace" in arg for arg in create)
    assert f"/workspace:rw,size=536870912,mode=0700,uid={os.getuid()},gid={os.getgid()}" in create
    assert create[create.index("--network") + 1] == "none"
    assert "--read-only" in create and "no-new-privileges" in create
    assert "symlinks=True" in create[-1]
