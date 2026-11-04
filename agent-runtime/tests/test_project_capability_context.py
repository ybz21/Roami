import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.swarm_memory import digest, from_project


def project_files():
    content = "Read the current connector and record only real dated observations."
    return {
        "teamMemory": "Actual decisions",
        "teamMemorySha256": digest("Actual decisions"),
        "mainInstructions": "Use this project's confirmed definitions.",
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


@pytest.mark.parametrize(
    "field,value", [("path", "../other/SKILL.md"), ("sha256", "fake"), ("content", "")]
)
def test_unverified_or_foreign_skill_does_not_reach_execution_context(field, value):
    files = project_files()
    files["skills"][0][field] = value
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project({"projectFiles": files})
