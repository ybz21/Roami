import pytest

from roami_agent.executors.targets import TargetDirectory
from roami_agent.storage.database import Database


@pytest.fixture
async def store(tmp_path):
    database = Database(tmp_path / "database/agents/runtime.db", tmp_path, managed=False)
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def mock_executor_catalog(monkeypatch):
    async def executors(self, commands=None):
        return {
            "version": 1,
            "candidates": [
                {"kind": kind, "installed": True, "tracked": True, "interactive": True}
                for kind in ("codex", "claude", "opencode", "pi")
            ],
        }

    # Mock launches must not discover executors through the developer's installed CLI.
    monkeypatch.setattr(TargetDirectory, "executors", executors)
