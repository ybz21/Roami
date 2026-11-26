"""Project operations exposed to members of the bound Swarm."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_okr import swarm_memory
from roami_okr.connector_batch_receipts import connector_batch_receipt
from roami_okr.memory_edit import (
    memory_edit_fields,
    memory_edit_payload,
    memory_edit_receipt,
)
from roami_okr.review import (
    checked_review,
    review_fields,
    review_payload,
    review_receipt,
)


def register_swarm_project_tools(registry, swarms, *, main, status):
    async def memory_edit(args, binding):
        info = await main(binding, args["swarmId"])
        if info["archived"]:
            raise DomainError("SWARM_ARCHIVED", 409)
        from roami_agent.storage.swarm_repository import changed, group

        workspace = await swarm_memory.project_context(swarms, binding["owner"], args["swarmId"])
        if (
            not workspace
            or (workspace.get("projectFiles") or {}).get("memoryEditsSupported") is not True
        ):
            raise DomainError("PROJECT_MEMORY_EDIT_UNAVAILABLE", 409)
        payload = memory_edit_payload(args, binding)
        result = await swarm_memory.project_context(
            swarms, binding["owner"], args["swarmId"], memory=payload
        )
        receipt = memory_edit_receipt(result, workspace["projectId"], payload["operationKey"])
        await swarms.db.call(
            lambda db: changed(
                db, group(db, binding["owner"], args["swarmId"]), "swarm.memory_changed"
            ),
            write=True,
        )
        return receipt

    async def project_read(args, binding):
        await status(args, binding)

        workspace = await swarm_memory.project_context(swarms, binding["owner"], args["swarmId"])
        if workspace is None:
            raise DomainError("SWARM_PROJECT_REQUIRED", 409)
        return workspace

    async def project_update(args, binding):
        info = await main(binding, args["swarmId"])
        if info["archived"]:
            raise DomainError("SWARM_ARCHIVED", 409)
        if args["operation"] == "review":
            args = {**args, "payload": checked_review(args["payload"])}
        expected = binding.get("coordinationProjectWrite")
        if (
            expected
            and expected["kind"] != "connector_batch"
            and (info.get("teamMemory") or {}).get("operationReceiptsSupported") is not True
        ):
            raise DomainError("SWARM_PROJECT_WRITE_RECEIPTS_UNAVAILABLE", 503)

        try:
            workspace = await swarm_memory.project_context(
                swarms,
                binding["owner"],
                args["swarmId"],
                operation=args["operation"],
                payload=args["payload"],
            )
        except DomainError as error:
            batch = args["payload"].get("batch")
            if (
                error.code == "OKR_CONFLICT"
                and args["operation"] == "record"
                and isinstance(batch, dict)
            ):
                try:
                    current = await swarm_memory.project_context(
                        swarms, binding["owner"], args["swarmId"]
                    )
                    if not current or current.get("projectId") != (info.get("scope") or {}).get(
                        "projectId"
                    ):
                        raise DomainError("SWARM_PROJECT_SCOPE_CONFLICT", 403)
                    confirmed = connector_batch_receipt(current, batch.get("id"))
                except DomainError:
                    confirmed = None
                if confirmed and confirmed["status"] == "confirmed":
                    raise DomainError(
                        "CONNECTOR_BATCH_ALREADY_CONFIRMED_REQUEST_CONFLICT", 409
                    ) from error
            raise
        if workspace is None:
            raise DomainError("SWARM_PROJECT_REQUIRED", 409)
        if binding.get("coordinationProjectWrite"):
            from roami_okr.coordination_writes import project_receipt

            return project_receipt(workspace, binding["coordinationProjectWrite"])
        return workspace

    async def project_review(args, binding):
        if binding.get("role") == "worker":
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        info = await main(binding, args["swarmId"])
        if info["archived"]:
            raise DomainError("SWARM_ARCHIVED", 409)
        if (info.get("teamMemory") or {}).get("operationReceiptsSupported") is not True:
            raise DomainError("PROJECT_REVIEW_RECEIPTS_UNAVAILABLE", 503)
        project_id = (info.get("scope") or {}).get("projectId")
        if not project_id:
            raise DomainError("SWARM_PROJECT_REQUIRED", 409)
        payload = review_payload(
            {key: value for key, value in args.items() if key != "swarmId"}, binding
        )

        workspace = await swarm_memory.project_context(
            swarms, binding["owner"], args["swarmId"], operation="review", payload=payload
        )
        return review_receipt(workspace, project_id, payload)

    registry.add(
        Tool(
            "swarm_project_review",
            "Save an evidence-based review in this original Main's project Swarm. Read the current project "
            "context first; pass its actual revision, real summary and optional actions. The host preserves "
            "the existing batch/request review identity and returns the saved review receipt. Do not probe "
            "fields with test writes or mistake a saved review for publication or goal completion.",
            object_schema(
                {"swarmId": {"type": "string", "minLength": 1}, **review_fields()},
                ["swarmId", "revision", "summary"],
            ),
            project_review,
            main=True,
            effect="write",
        )
    )

    async def project_batch(args, binding):
        info = await main(binding, args["swarmId"])

        workspace = await swarm_memory.project_context(swarms, binding["owner"], args["swarmId"])
        if workspace is None:
            raise DomainError("SWARM_PROJECT_REQUIRED", 409)
        if workspace.get("projectId") != (info.get("scope") or {}).get("projectId"):
            raise DomainError("SWARM_PROJECT_SCOPE_CONFLICT", 403)
        return connector_batch_receipt(workspace, args["batchId"])

    string = {"type": "string", "minLength": 1}
    for name, description, schema, call, is_main, effect in [
        (
            "swarm_memory_edit",
            (
                "Project Main edits exact unique team-memory fragments with the last read SHA. "
                "Read swarm_memory_read first. Supply oldText/newText edits, not the full document. "
                "All edits match the original once each and cannot overlap. The host preserves "
                "history and retry identity; read back actual memory before claiming a rule changed. "
                "Append adds knowledge and does not edit earlier rules. No paths or secrets."
            ),
            object_schema(
                {"swarmId": string, **memory_edit_fields()}, ["swarmId", "expectedSha256", "edits"]
            ),
            memory_edit,
            True,
            "write",
        ),
        (
            "swarm_project_context",
            "Read the bound project's current flat OKR workspace: definitions, dashboard, observations, reviews, instructions and team memory. For one Connector confirmation use swarm_connector_batch. If this full context is externalized, read the retained artifact; its preview is incomplete and may show only old receipts. No shell or host paths. Missing project bundles remain unavailable.",
            object_schema({"swarmId": string}, ["swarmId"]),
            project_read,
            True,
            "read",
        ),
        (
            "swarm_project_update",
            "Apply a user-authorized OKR change to this Main swarm's bound registered project using its current revision. Read swarm_project_context first. Payload is exactly the operation's JSON body. For Connector retries, first read swarm_connector_batch with the same batchId: confirmed means already committed even after revision advances. Preserve the complete original request including note; CONNECTOR_BATCH_ALREADY_CONFIRMED_REQUEST_CONFLICT never invalidates old facts. Read its receipt, do not resubmit or claim it was discarded. No shell, host paths, credentials, model routes or public publication.",
            object_schema(
                {
                    "swarmId": string,
                    "operation": {
                        "type": "string",
                        "enum": ["save", "collect", "record", "review", "sync"],
                    },
                    "payload": {"type": "object"},
                },
                ["swarmId", "operation", "payload"],
            ),
            project_update,
            True,
            "write",
        ),
        (
            "swarm_connector_batch",
            "Read one confirmed Connector batch receipt from this Main's bound project. Use the same batchId after an unknown result or conflict, without replaying a write. confirmed remains a historical fact after reviews or new publications; not_found is not permission to submit again. Returns current workspace revision separately from the original receipt revision. Full source evidence stays in project context.",
            object_schema(
                {"swarmId": string, "batchId": {"type": "string", "pattern": "^[a-f0-9]{32}$"}},
                ["swarmId", "batchId"],
            ),
            project_batch,
            True,
            "read",
        ),
    ]:
        registry.add(Tool(name, description, schema, call, main=is_main, effect=effect))
