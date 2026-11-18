"""Resolve persisted native provider directories before admitting Main or member jobs."""

from roami_agent.storage.database import row, rows


def native_job_binding(db, job):
    if job["kind"] == "turn.run":
        value = row(
            db,
            "SELECT p.binding_json FROM turns t JOIN conversations c ON c.id=t.conversation_id JOIN project_okr_mains m "
            "ON m.conversation_id=t.conversation_id AND m.owner_id=c.owner_id "
            "JOIN project_okr_main_providers p ON p.owner_id=m.owner_id "
            "AND p.project_id=m.project_id AND p.conversation_id=m.conversation_id "
            "WHERE t.id=? AND NOT EXISTS(SELECT 1 FROM project_okr_main_providers newer "
            "WHERE newer.owner_id=p.owner_id AND newer.project_id=p.project_id "
            "AND newer.generation>p.generation)",
            (job["aggregate_id"],),
        )
    elif job["kind"] == "task.run":
        value = row(
            db,
            "SELECT p.binding_json FROM swarm_member_provider_generations p "
            "JOIN swarm_members m ON m.id=p.member_id AND m.execution_generation=p.generation "
            "JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id "
            "JOIN swarm_work_items w ON w.id=b.work_id AND w.execution_generation=p.generation "
            "WHERE w.task_id=? AND p.executor=w.executor AND p.model=w.model",
            (job["aggregate_id"],),
        )
    else:
        return None
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
