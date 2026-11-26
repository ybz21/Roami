"""Resolve the native directory of a bound member task."""

from roami_agent.storage.database import row


def native_member_binding(db, task_id):
    value = row(
        db,
        "SELECT p.binding_json FROM swarm_member_provider_generations p "
        "JOIN swarm_members m ON m.id=p.member_id AND m.execution_generation=p.generation "
        "JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id "
        "JOIN swarm_work_items w ON w.id=b.work_id AND w.execution_generation=p.generation "
        "WHERE w.task_id=? AND p.executor=w.executor AND p.model=w.model",
        (task_id,),
    )
    return value["binding_json"] if value else None
