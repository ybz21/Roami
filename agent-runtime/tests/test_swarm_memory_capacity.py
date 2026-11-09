import hashlib

from roami_agent.storage.swarm_memory import from_project


def test_memory_capacity_counts_utf8_bytes_not_characters():
    content = "已验证的团队知识" * 2000
    result = from_project(
        {
            "projectFiles": {
                "teamMemory": content,
                "teamMemorySha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        }
    )
    assert result["sizeBytes"] == len(content.encode()) > len(content)
    assert result["limitBytes"] == 65536
    assert result["content"] == content
