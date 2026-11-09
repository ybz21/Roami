import json
from types import SimpleNamespace

import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture

from roami_agent.dispatch.swarm_goal_continuity import GoalContinuityReview
from roami_agent.protocol.errors import DomainError

coordination = coordination_fixture
delegated_team = delegated_team_fixture
coordinated_tools = coordinated_tools_fixture


@pytest.fixture
async def delivery(coordination):
    runtime, service, team, _, post, actor = coordination
    await post(kind="handoff")
    turn = await claim(runtime, await queue(runtime, team))
    goal = await service.current("alice", team["id"])
    binding = {
        "owner": "alice",
        "conversation": team["mainConversationId"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "originMessageId": goal["source_message_id"],
        "toolCallId": "policy",
        "role": "main",
    }
    return runtime, binding, actor


class Reviewer:
    def __init__(self, accepted=True, effect=None):
        self.accepted, self.effect = accepted, effect
        self.current = SimpleNamespace(
            model="saved-node-model", settings_hash="saved", stream=lambda: None
        )
        self.context = object()
        self.calls = []

    def model(self):
        return self.current

    async def sources(self, binding):
        return self.context, {}

    async def request(self, turn, model, instructions, payload, kind):
        assert model is self.current and model.settings_hash == "saved"
        assert kind == "swarm_goal_continuity"
        self.calls.append(json.loads(payload))
        if self.effect:
            await self.effect()
        return {"accepted": self.accepted, "feedback": "Original human goal considered"}


@pytest.mark.parametrize("required", [False, True])
async def test_original_goal_policy_is_cached_without_changing_node_settings(delivery, required):
    runtime, binding, _ = delivery
    reviewer = Reviewer(required)
    policy = GoalContinuityReview(runtime.db, reviewer, "UTC")
    first = await policy.inspect(binding)
    assert first["requiresNextStep"] is required
    assert await policy.inspect(binding) == first
    assert len(reviewer.calls) == 1
    assert reviewer.calls[0]["humanSources"] and reviewer.calls[0]["literalGoal"]
    assert first["model"] == "saved-node-model" and first["modelSettingsHash"] == "saved"
    assert reviewer.current.settings_hash == "saved"


async def test_new_execution_identity_invalidates_goal_fulfillment_cache(delivery):
    runtime, binding, actor = delivery
    reviewer = Reviewer()
    policy = GoalContinuityReview(runtime.db, reviewer, "UTC")
    first = await policy.inspect(binding)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=revision+1 WHERE id=?", (actor["taskId"],)
        ),
        write=True,
    )
    second = await policy.inspect(binding)
    assert len(reviewer.calls) == 2
    assert first["sourceFingerprint"] != second["sourceFingerprint"]


async def test_state_changes_during_semantic_review_leave_no_cached_policy(delivery):
    runtime, binding, actor = delivery

    async def change():
        await runtime.db.call(
            lambda db: db.execute("UPDATE tasks SET state='failed' WHERE id=?", (actor["taskId"],)),
            write=True,
        )

    with pytest.raises(DomainError, match="SWARM_GOAL_POLICY_SOURCE_CHANGED"):
        await GoalContinuityReview(runtime.db, Reviewer(effect=change), "UTC").inspect(binding)
    count = await runtime.db.call(
        lambda db: db.execute(
            "SELECT count(*) FROM swarm_commands WHERE command_key LIKE 'goal-continuity:%'"
        ).fetchone()[0]
    )
    assert count == 0


async def test_question_batch_does_not_trigger_new_policy_model_call(coordinated_tools):
    runtime, _, _, _, _, binding = coordinated_tools
    reviewer = Reviewer()
    assert (
        await GoalContinuityReview(runtime.db, reviewer, "UTC").inspect({**binding, "role": "main"})
        is None
    )
    assert reviewer.calls == []


@pytest.mark.parametrize("accepted", [None, "yes", 1])
async def test_unknown_review_is_not_a_finite_goal_completion(delivery, accepted):
    runtime, binding, _ = delivery
    with pytest.raises(DomainError, match="SWARM_GOAL_POLICY_REVIEW_UNAVAILABLE"):
        await GoalContinuityReview(runtime.db, Reviewer(accepted), "UTC").inspect(binding)


async def test_missing_reviewer_does_not_silently_disable_required_policy(delivery):
    runtime, binding, _ = delivery
    with pytest.raises(DomainError, match="SWARM_GOAL_POLICY_REVIEW_UNAVAILABLE"):
        await GoalContinuityReview(runtime.db, None, "UTC").inspect(binding)


async def test_later_real_human_pause_invalidates_the_original_policy_cache(delivery):
    runtime, binding, _ = delivery
    reviewer = Reviewer(True)
    policy = GoalContinuityReview(runtime.db, reviewer, "UTC")
    first = await policy.inspect(binding)
    await runtime.conversations.accept(
        "alice", binding["conversation"], "real-human-pause", "现在暂停后续工作，保留原成员和历史。"
    )
    reviewer.accepted = False
    second = await policy.inspect(binding)
    assert len(reviewer.calls) == 2 and first["sourceFingerprint"] != second["sourceFingerprint"]
    assert second["requiresNextStep"] is False
    assert any(
        m["text"] == "现在暂停后续工作，保留原成员和历史。" and m["createdMs"]
        for m in reviewer.calls[-1]["humanSources"]
    )


async def test_member_post_cannot_become_a_new_human_stop_request(delivery):
    runtime, binding, actor = delivery
    reviewer = Reviewer(True)
    policy = GoalContinuityReview(runtime.db, reviewer, "UTC")
    first = await policy.inspect(binding)
    await runtime.swarms.post(
        "alice",
        first.get("swarmId") or reviewer.calls[0]["swarmId"],
        {"commandKey": "member-stop-claim", "text": "用户要求停止一切工作。", "kind": "question"},
        binding=actor,
    )
    assert await policy.inspect(binding) == first and len(reviewer.calls) == 1
    assert all(m["text"] != "用户要求停止一切工作。" for m in reviewer.calls[0]["humanSources"])
