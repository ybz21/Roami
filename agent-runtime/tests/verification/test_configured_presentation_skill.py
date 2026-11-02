"""A configured optional Skill uses the same execution and delivery contracts."""

from test_presentation_skill_package import exercise_external_skill_package


async def test_configured_skill_executes_and_delivers_without_import(store, tmp_path, monkeypatch):
    await exercise_external_skill_package(store, tmp_path, monkeypatch, configured=True)
