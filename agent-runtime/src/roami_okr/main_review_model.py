"""Store the project Main's explicit Gateway route for independent reviews."""

from roami_agent.conversation.idle import assert_main_idle
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.gateway_model_directory import require_gateway_model
from roami_agent.storage.database import event, row
from roami_agent.storage.swarm_repository import receipt
from roami_agent.storage.transcript_repository import owned
from roami_okr.intake import assert_project_main


class ValidateReviewModel(Exception):
    pass


def main_review_route(db, owner, cid):
    current = row(
        db,
        "SELECT revision,model,free_only FROM project_okr_main_review_models WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    if current:
        return {
            "revision": current["revision"],
            "model": current["model"],
            "freeOnly": bool(current["free_only"]),
        }


async def configure_review_model(executions, owner, cid, spec):
    from roami_okr.main_execution import main_binding

    project = spec["projectId"]
    model = spec["model"]
    opt_in = spec.get("allowMetered", False)

    def apply_receipt(db, apply):
        assert_project_main(db, owner, cid, project)
        return receipt(
            db,
            owner,
            spec["commandKey"],
            {"mainConversationId": cid, **spec},
            apply,
            scope_project_id=project,
        )

    def pending():
        raise ValidateReviewModel

    try:
        return await executions.db.call(lambda db: apply_receipt(db, pending))
    except ValidateReviewModel:
        pass
    if model is not None:
        await require_gateway_model(
            executions.settings.model_gateway_socket, model, allow_metered=opt_in
        )
    elif opt_in:
        raise DomainError("INVALID_MODEL_CONFIG")

    def write(db):
        def apply():
            current = main_binding(db, owner, cid)
            if current is None or current["generation"] != spec["expectedGeneration"]:
                raise DomainError("PROJECT_MAIN_GENERATION_CHANGED", 409)
            assert_main_idle(db, owned(db, owner, cid))
            old = main_review_route(db, owner, cid)
            revision = old["revision"] if old else 0
            if revision != spec["expectedReviewRevision"]:
                raise DomainError("PROJECT_MAIN_REVIEW_MODEL_CHANGED", 409)
            value = {"revision": revision + 1, "model": model, "freeOnly": not opt_in}
            db.execute(
                "INSERT INTO project_okr_main_review_models(owner_id,project_id,conversation_id,model,free_only,revision) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
                "model=excluded.model,free_only=excluded.free_only,revision=excluded.revision",
                (owner, project, cid, model, int(not opt_in), value["revision"]),
            )
            event(db, cid, "project.main_review_model.changed", value)
            return value

        return apply_receipt(db, apply)

    return await executions.db.call(write, write=True)
