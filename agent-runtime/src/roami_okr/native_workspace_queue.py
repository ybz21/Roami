"""Resolve persisted project Main directories for the scheduler's directory guards."""

from roami_agent.storage.database import row, rows


def native_turn_binding(db, turn_id):
    value = row(
        db,
        "SELECT p.binding_json FROM turns t JOIN conversations c ON c.id=t.conversation_id JOIN project_okr_mains m "
        "ON m.conversation_id=t.conversation_id AND m.owner_id=c.owner_id "
        "JOIN project_okr_main_providers p ON p.owner_id=m.owner_id "
        "AND p.project_id=m.project_id AND p.conversation_id=m.conversation_id "
        "WHERE t.id=? AND NOT EXISTS(SELECT 1 FROM project_okr_main_providers newer "
        "WHERE newer.owner_id=p.owner_id AND newer.project_id=p.project_id "
        "AND newer.generation>p.generation)",
        (turn_id,),
    )
    return value["binding_json"] if value else None


def running_native_mains(db):
    return rows(
        db,
        "SELECT t.id,p.binding_json AS native_binding_json FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "JOIN project_okr_mains m ON m.conversation_id=t.conversation_id AND m.owner_id=c.owner_id "
        "JOIN project_okr_main_providers p ON p.owner_id=m.owner_id AND p.project_id=m.project_id "
        "AND p.conversation_id=m.conversation_id WHERE t.state='running' "
        "AND NOT EXISTS(SELECT 1 FROM project_okr_main_providers newer "
        "WHERE newer.owner_id=p.owner_id AND newer.project_id=p.project_id "
        "AND newer.generation>p.generation)",
    )
