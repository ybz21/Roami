import pytest

from roami_agent.storage.database import Database


@pytest.fixture
async def store(tmp_path):
    database = Database(tmp_path / "database/agents/runtime.db", tmp_path, managed=False)
    await database.open()
    yield database
    await database.close()
