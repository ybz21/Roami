import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination import delegated_team as delegated_team_fixture
from test_swarm_result_observations import report

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.swarm_memory import digest
from roami_okr.swarm_memory import from_project

coordination = coordination_fixture
delegated_team = delegated_team_fixture


def project_files():
    content = "Read the current connector and record only real dated observations."
    return {
        "teamMemory": "Actual decisions",
        "teamMemorySha256": digest("Actual decisions"),
        "mainInstructions": "Use this project's confirmed definitions.",
        "workflow": "Read daily files and report task/revision/run to Main.",
        "skills": [
            {
                "id": "metric-collection",
                "path": "skills/metric-collection/SKILL.md",
                "content": content,
                "sha256": digest(content),
            }
        ],
    }


def test_project_skills_and_instructions_reach_same_shared_team_context():
    files = project_files()
    value = from_project({"projectFiles": files})
    assert value["source"] == ".roami/okr/memory/team.md"
    assert value["content"] == "Actual decisions"
    assert value["projectGuidance"]["skills"] == files["skills"]
    assert value["projectGuidance"]["instructions"] == files["mainInstructions"]
    assert value["projectGuidance"]["workflow"] == files["workflow"]
    assert value["projectGuidance"]["workflowSource"] == ".roami/okr/AGENTS.md"


async def test_native_coordination_references_project_guidance_and_keeps_authority(
    coordination, monkeypatch
):
    runtime, _, team, _, _, actor = coordination
    files = project_files()
    memory = from_project({"projectFiles": files})
    calls = []

    async def read(owner, sid):
        calls.append((owner, sid))
        return memory

    monkeypatch.setattr(runtime.swarms, "memory_read", read)
    await report(runtime, actor)
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    plan, prompt = await runtime.loop.context.build(
        {**turn, "native_project_main": True}, "Main rules", [], None
    )
    assert calls == [("alice", team["id"])]
    assert plan["coordinationEvidence"]["batchId"] == batch["batchId"]
    assert len(plan["coordinationEvidence"]["resultReceiptIds"]) == 1
    instructions = prompt[0]["content"]
    assert files["mainInstructions"] in instructions and files["teamMemory"] in instructions
    assert (
        files["workflow"] not in instructions and files["skills"][0]["content"] not in instructions
    )
    assert digest(files["workflow"]) in instructions
    assert (
        files["skills"][0]["path"] in instructions and files["skills"][0]["sha256"] in instructions
    )

    _, full_prompt = await runtime.loop.context.build(turn, "Main rules", [], None)
    assert files["workflow"] in full_prompt[0]["content"]
    assert files["skills"][0]["content"] in full_prompt[0]["content"]
    assert (await runtime.swarms.memory_read("alice", team["id"]))["projectGuidance"][
        "workflow"
    ] == (files["workflow"])


@pytest.mark.parametrize(
    "field,value", [("path", "../other/SKILL.md"), ("sha256", "fake"), ("content", "")]
)
def test_unverified_or_foreign_skill_does_not_reach_execution_context(field, value):
    files = project_files()
    files["skills"][0][field] = value
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project({"projectFiles": files})
