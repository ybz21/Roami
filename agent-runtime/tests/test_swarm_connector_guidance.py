import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.swarm_memory import digest, from_project


def project_workspace(project_count=1, connector_count=1):
    skills = [
        {
            "id": f"role-{i}",
            "path": f"skills/role-{i}/SKILL.md",
            "content": "Role",
            "sha256": digest("Role"),
        }
        for i in range(project_count)
    ]
    skills += [
        {
            "id": f"connector-source-{i}",
            "path": f"connectors/source-{i}/SKILL.md",
            "content": "Collect",
            "sha256": digest("Collect"),
        }
        for i in range(connector_count)
    ]
    return {
        "projectFiles": {
            "teamMemory": "Original knowledge",
            "teamMemorySha256": digest("Original knowledge"),
            "operationReceiptsSupported": True,
            "skills": skills,
        }
    }


@pytest.mark.parametrize("project_count,connector_count", [(1, 1), (16, 32), (0, 32)])
def test_go_connector_guidance_keeps_team_memory_and_receipt_capability(
    project_count, connector_count
):
    workspace = project_workspace(project_count, connector_count)
    result = from_project(workspace)
    assert result["available"] is True
    assert result["content"] == "Original knowledge"
    assert result["sha256"] == digest("Original knowledge")
    assert result["operationReceiptsSupported"] is True
    assert result["projectGuidance"]["skills"] == workspace["projectFiles"]["skills"]


def test_go_connector_identifier_can_use_the_full_confirmed_source_name():
    workspace = project_workspace(0, 1)
    name = "x" * 64
    workspace["projectFiles"]["skills"][0].update(
        id="connector-" + name, path=f"connectors/{name}/SKILL.md"
    )
    assert from_project(workspace)["available"]


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "source-0"},
        {"id": "connector-", "path": "connectors//SKILL.md"},
        {"path": "connectors/other/SKILL.md"},
        {"path": "connectors/source-0/../SKILL.md"},
        {"path": "/connectors/source-0/SKILL.md"},
        {"path": "skills/source-0/SKILL.md"},
        {"sha256": "a" * 64},
        {"content": "Changed"},
    ],
)
def test_connector_guidance_rejects_mismatched_identity_path_and_bytes(changes):
    workspace = project_workspace(0, 1)
    workspace["projectFiles"]["skills"][0].update(changes)
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project(workspace)


@pytest.mark.parametrize("project_count,connector_count", [(17, 0), (0, 33)])
def test_guidance_enforces_each_go_package_limit(project_count, connector_count):
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project(project_workspace(project_count, connector_count))


def test_connector_guidance_still_rejects_duplicates_and_excessive_context():
    workspace = project_workspace(0, 1)
    workspace["projectFiles"]["skills"] *= 2
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project(workspace)
    workspace = project_workspace(0, 1)
    content = "x" * 65537
    workspace["projectFiles"]["skills"][0].update(content=content, sha256=digest(content))
    with pytest.raises(DomainError, match="SWARM_PROJECT_MEMORY_UNAVAILABLE"):
        from_project(workspace)
