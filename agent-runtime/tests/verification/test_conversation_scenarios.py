"""Full multi-turn conversations and negative controls for the independent task oracle."""

import copy
import json
import runpy
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from roami_agent.improvement.evaluation.conversation_actor import ScriptedConversationActor
from roami_agent.improvement.evaluation.conversation_oracle import grade_checkpoint
from roami_agent.improvement.evaluation.conversation_scenarios import run_conversation
from roami_agent.improvement.integrations.tool_process import logged_tool_process
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.tools.command_families import COMMANDS

REPOSITORY = Path(__file__).parents[3]
SCENARIOS = [
    scenario
    for path in sorted((REPOSITORY / "cases").glob("case-9[5678]-*/input/conversations.json"))
    for scenario in json.loads(path.read_text())["scenarios"]
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario["id"])
async def test_complete_conversation_checks_each_real_runtime_turn(tmp_path, scenario):
    result = await run_conversation(scenario, tmp_path / "episode")
    assert result["passed"], result
    assert len(result["checkpoints"]) == len(scenario["turns"])
    assert result["mode"] == "protocol_fixture"
    assert not result["live_model_semantics_tested"] and not result["eligible_for_promotion"]
    assert result["metrics"]["token_coverage"] == "complete"


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "missing",
        "revision",
        "requirements",
        "mixed",
        "executor",
        "inputs",
        "wrong_task",
        "attempts",
        "question",
    ],
)
def test_independent_oracle_rejects_wrong_task_construction(fault):
    task = {
        "id": "original",
        "goal": "名册 保留Markdown",
        "revision": 2,
        "executor": "codex",
        "attachments": ["a.png"],
        "conversation_id": "c",
        "attempt_count": 2,
        "current_run_count": 1,
        "project_id": "maple",
    }
    snapshot = {
        "conversation_id": "c",
        "tasks": [task],
        "answer": "",
        "tools": [],
        "question": True,
        "turn_state": "completed",
        "pending_steers": 0,
    }
    spec = {
        "alias": "名册",
        "match": "名册",
        "revision": 2,
        "contains": ["保留Markdown"],
        "excludes": ["其他任务"],
        "executor": "codex",
        "attachments": ["a.png"],
    }
    expected = {"task_count": 1, "tasks": [spec], "question": True}
    if fault == "extra":
        snapshot["tasks"].append({**task, "id": "extra"})
    elif fault == "missing":
        snapshot["tasks"] = []
    elif fault == "question":
        snapshot["question"] = False
    else:
        field, value = {
            "revision": ("revision", 1),
            "requirements": ("goal", "名册"),
            "mixed": ("goal", "名册 保留Markdown 其他任务"),
            "executor": ("executor", "claude"),
            "inputs": ("attachments", []),
            "wrong_task": ("id", "replacement"),
            "attempts": ("current_run_count", 2),
        }[fault]
        task[field] = value
    result = grade_checkpoint(expected, snapshot, {"名册": "original"})
    assert not result["passed"] and result["failures"]


async def test_live_actor_does_not_receive_fixture_or_expected_answer(tmp_path):
    scenario = copy.deepcopy(SCENARIOS[0])
    scenario["turns"] = scenario["turns"][:1]
    scenario["turns"][0]["fixture"] = [{"text": "FIXTURE-SECRET-NEVER-SEND"}]
    scenario["turns"][0]["expect"]["reply_json"] = {"secret": "ORACLE-SECRET-NEVER-SEND"}

    class Actor:
        model = "unbiased-fixture-transport"

        async def stream(self, messages, tools):
            assert "FIXTURE-SECRET-NEVER-SEND" not in json.dumps(messages)
            assert "ORACLE-SECRET-NEVER-SEND" not in json.dumps(messages)
            yield ModelEvent("text", '{"主题":"读书会","人数":30,"预算":3000}')
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    result = await run_conversation(scenario, tmp_path / "independent", provider=Actor())
    assert not result["passed"]
    assert result["checkpoints"][0]["failures"] == ["CHAT_CONSTRAINTS_MISMATCH"]


async def test_failed_or_unknown_usage_stops_before_next_user_turn(tmp_path):
    scenario = copy.deepcopy(SCENARIOS[0])
    calls = 0

    class UnknownUsage:
        model = "unknown-usage-control"

        async def stream(self, messages, tools):
            nonlocal calls
            calls += 1
            yield ModelEvent("text", '{"主题":"读书会","人数":30,"预算":3000}')

    result = await run_conversation(scenario, tmp_path / "unknown", provider=UnknownUsage())
    assert not result["passed"] and result["failure"] == "RSI_USAGE_UNKNOWN"
    assert calls == len(result["checkpoints"]) == 1


@pytest.mark.parametrize("answer,passed", [("true", False), ("1.0", True), ('"1"', False)])
def test_json_numbers_and_booleans_keep_their_actual_types(answer, passed):
    snapshot = {
        "tasks": [],
        "conversation_id": "c",
        "answer": answer,
        "tools": [],
        "question": False,
        "turn_state": "completed",
        "pending_steers": 0,
    }
    result = grade_checkpoint({"task_count": 0, "reply_json": 1}, snapshot, {})
    assert result["passed"] is passed


def test_task_prohibitions_require_preserved_user_sources_without_literal_goal_wording():
    task = {
        "id": "a",
        "goal": "不要发送任何消息",
        "user_contract": "生成名单，不发通知",
        "revision": 1,
        "executor": "native",
        "attachments": [],
        "conversation_id": "c",
        "attempt_count": 1,
        "current_run_count": 1,
    }
    snapshot = {
        "tasks": [task],
        "conversation_id": "c",
        "answer": "",
        "tools": [],
        "question": False,
        "turn_state": "completed",
        "pending_steers": 0,
    }
    expected = {
        "task_count": 1,
        "tasks": [
            {"alias": "名单", "match": "名单", "revision": 1, "source_contains": ["不发通知"]}
        ],
    }
    assert grade_checkpoint(expected, snapshot, {"名单": "a"})["passed"]
    task["user_contract"] = "生成名单"
    assert not grade_checkpoint(expected, snapshot, {"名单": "a"})["passed"]


def test_all_scenarios_have_independent_turn_oracles_and_real_attachment_inputs():
    assert len(SCENARIOS) == 16 and sum(len(s["turns"]) for s in SCENARIOS) == 62
    assert len({s["id"] for s in SCENARIOS}) == len(SCENARIOS)
    for scenario in SCENARIOS:
        assert all(
            step["text"] and step["fixture"] and "task_count" in step["expect"]
            for step in scenario["turns"]
        )
    inputs = next(s for s in SCENARIOS if s["id"] == "steer-inputs-with-unrelated-chat-image")
    assert inputs["turns"][1]["attachments"] == ["other-topic.png"]


async def test_missing_saved_gateway_records_preflight_failure_without_model_calls(
    tmp_path, monkeypatch
):
    module = runpy.run_path(str(REPOSITORY / "scripts/dev/run-conversation-scenarios.py"))
    function = module["episodes"]

    async def blocked(config, root):
        raise DomainError("RSI_SHARED_MODEL_GATEWAY_REQUIRED")

    def forbidden(*args):
        pytest.fail("Unbound saved model must not construct a provider")

    monkeypatch.setitem(function.__globals__, "node_model_settings", blocked)
    monkeypatch.setitem(function.__globals__, "configured_provider", forbidden)
    args = SimpleNamespace(
        mode="saved-model",
        agent_config=tmp_path / "node.toml",
        data_root=tmp_path / "node",
        output=tmp_path,
    )
    assert await function(args, []) == 1
    receipt = json.loads((tmp_path / "episodes.json").read_text())
    assert receipt["failure"] == "RSI_SHARED_MODEL_GATEWAY_REQUIRED"
    assert receipt["results"] == [] and receipt["usage_known"] is True


async def test_live_profile_cannot_execute_a_host_shell_command(tmp_path):
    scenario = copy.deepcopy(SCENARIOS[0])
    scenario["turns"] = scenario["turns"][:1]
    outside = tmp_path / "must-not-exist"

    class Actor:
        model = "shell-boundary-control"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "host-write",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {
                                    "scope": "host",
                                    "argv": [
                                        "python3",
                                        "-c",
                                        f"from pathlib import Path; Path({str(outside)!r}).touch()",
                                    ],
                                }
                            ),
                        },
                    },
                )
            else:
                assert json.loads(messages[-1]["content"])["error"] == "TOOL_UNAVAILABLE"
                yield ModelEvent("text", '{"主题":"读书会","人数":30,"预算":3000}')
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    result = await run_conversation(scenario, tmp_path / "contained", provider=Actor())
    assert result["passed"] and not outside.exists()
    metrics = result["metrics"]
    assert metrics["tool_calls"] == metrics["tool_errors"] == 1
    assert metrics["tool_admission_failures"] == 1
    assert metrics["tool_error_rate"] == 1
    assert metrics["tool_first_attempt_success_rate"] == 0
    assert logged_tool_process(tmp_path / "contained")["tool_errors"] == 1


async def test_scenario_uses_current_main_schemas_and_executes_compact_registered_commands(
    tmp_path, monkeypatch
):
    from roami_agent.improvement.evaluation import conversation_scenarios

    scenario = next(s for s in SCENARIOS if s["id"] == "ambiguous-followup-needs-target-choice")

    class CompactActor(ScriptedConversationActor):
        def __init__(self):
            super().__init__()
            self.seen = set()

        def turn(self, actions):
            if actions[-1].get("tool") in {"delegate", "task_steer"}:
                actions = [*actions, {"text": "已提交。"}]
            super().turn(actions)

        async def stream(self, messages, tools):
            schemas = {t["function"]["name"]: t["function"]["parameters"] for t in tools}
            assert set(schemas["reply"]["properties"]) == {"text"}
            assert schemas["delegate"]["required"] == ["goal"]
            assert schemas["ask_user"]["properties"]["options"]["items"]["type"] == "string"
            assert "task_steer" not in schemas
            async for event in super().stream(messages, tools):
                if event.kind == "tool":
                    function = event.value["function"]
                    name = function["name"]
                    self.seen.add(name)
                    args = json.loads(function["arguments"])
                    if name == "delegate":
                        args = {"goal": args["goal"], "executor": "native"}
                    elif name == "ask_user":
                        args["options"] = [option["label"] for option in args["options"]]
                    elif name in {"task_status", "task_steer"}:
                        if name == "task_steer":
                            args = {key: args[key] for key in ("taskId", "text")}
                        command = ["roami", *COMMANDS[name], "--input", json.dumps(args)]
                        function["name"] = "bash"
                        args = {"command": shlex.join(command)}
                    function["arguments"] = json.dumps(args)
                yield event

    actor = CompactActor()
    monkeypatch.setattr(conversation_scenarios, "ScriptedConversationActor", lambda: actor)
    result = await run_conversation(scenario, tmp_path / "compact")
    assert result["passed"], result
    assert {"delegate", "ask_user", "task_status", "task_steer"} <= actor.seen
    assert result["metrics"]["tool_calls"] == 5
    assert result["metrics"]["tool_errors"] == 0
    assert result["metrics"]["tool_first_attempt_success_rate"] == 1


def test_identity_uses_source_turn_and_title_without_mistaking_boundary_mentions():
    tasks = [
        {
            "id": ident,
            "title": title,
            "goal": goal,
            "created_turn": 1,
            "revision": 1,
            "executor": "native",
            "attachments": [],
            "conversation_id": "c",
            "attempt_count": 1,
            "current_run_count": 1,
        }
        for ident, title, goal in [
            ("a", "周一清单Markdown", "生成周一清单，不修改周二清单"),
            ("b", "周二清单CSV", "生成周二清单，不修改周一清单"),
        ]
    ]
    snapshot = {
        "tasks": tasks,
        "conversation_id": "c",
        "answer": "",
        "tools": [],
        "question": False,
        "turn_state": "completed",
        "pending_steers": 0,
    }
    expected = {
        "task_count": 2,
        "tasks": [
            {"alias": name, "match": name, "created_turn": 1, "revision": 1}
            for name in ["周一清单", "周二清单"]
        ],
    }
    bindings = {}
    assert grade_checkpoint(expected, snapshot, bindings)["passed"]
    assert bindings == {"周一清单": "a", "周二清单": "b"}
    tasks[1]["title"], tasks[1]["goal"] = "无关任务", "错误的另一项工作"
    assert not grade_checkpoint(expected, snapshot, {})["passed"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_boundary_mentions_require_a_unique_match_for_frozen_output_requirements(ambiguous):
    tasks = [
        {
            "id": ident,
            "title": "",
            "goal": goal,
            "created_turn": 1,
            "revision": 1,
            "executor": "native",
            "conversation_id": "c",
            "attempt_count": 1,
            "current_run_count": 1,
        }
        for ident, goal in [
            ("a", "Create the north report in Markdown with columns name and group"),
            (
                "b",
                "Create the south report in CSV with columns item and quantity; keep the north report unchanged",
            ),
        ]
    ]
    if ambiguous:
        tasks[1]["goal"] += "; Markdown with columns name and group"
    snapshot = {
        "tasks": tasks,
        "conversation_id": "c",
        "answer": "",
        "tools": [],
        "turn_state": "completed",
        "pending_steers": 0,
    }
    expected = {
        "task_count": 2,
        "tasks": [
            {
                "alias": "north",
                "match": "north report",
                "created_turn": 1,
                "revision": 1,
                "contains": ["Markdown", "name", "group"],
            },
            {
                "alias": "south",
                "match": "south report",
                "created_turn": 1,
                "revision": 1,
                "contains": ["CSV", "item", "quantity"],
            },
        ],
    }
    bindings = {}
    assert grade_checkpoint(expected, snapshot, bindings)["passed"] is not ambiguous
    if not ambiguous:
        assert bindings == {"north": "a", "south": "b"}
        assert not grade_checkpoint(expected, snapshot, {"north": "b", "south": "a"})["passed"]


def test_single_task_can_be_identified_by_admission_source_without_ordinal_in_title():
    task = {
        "id": "a",
        "title": "名册模板",
        "goal": "预算：3000；人数 20 人",
        "created_turn": 2,
        "revision": 1,
        "executor": "native",
        "attachments": [],
        "conversation_id": "c",
        "attempt_count": 1,
        "current_run_count": 1,
    }
    snapshot = {
        "tasks": [task],
        "conversation_id": "c",
        "answer": "",
        "tools": [],
        "question": False,
        "turn_state": "completed",
        "pending_steers": 0,
    }
    expected = {
        "task_count": 1,
        "tasks": [
            {
                "alias": "第一份名册",
                "match": "第一份名册",
                "created_turn": 2,
                "revision": 1,
                "contains": ["预算3000", "20人"],
            }
        ],
    }
    assert grade_checkpoint(expected, snapshot, {})["passed"]
    task["goal"] = "预算：30.00；人数 20 人"
    assert not grade_checkpoint(expected, snapshot, {})["passed"]
    task["goal"], task["created_turn"] = "预算：3000；人数 20 人", 1
    assert not grade_checkpoint(expected, snapshot, {})["passed"]
