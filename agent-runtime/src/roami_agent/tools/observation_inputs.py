"""Bind tool actions to observations already delivered in the current task."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def resource_input(driver, args, binding, kind):
    if args.get("resourceId"):
        return args
    scope = await driver.resources.scope(binding)
    owned = [item for item in await driver.resources.owned(scope) if item["kind"] == kind]
    if len(owned) != 1:
        raise DomainError("RESOURCE_TARGET_REQUIRED", 409)
    return dict(args, resourceId=owned[0]["id"])


async def observation_input(driver, args, binding, kind):
    if args.get("observationId"):
        return args
    scope = await driver.resources.scope(binding, input_action=True)
    if kind == "desktop":
        manifest = await driver.db.call(
            lambda db: row(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
                (binding["turnId"],),
            )
        )
        images = json.loads(manifest["parts_json"]).get("imageEvidence", []) if manifest else []
        if len(images) != 1 or not images[0].get("observationId"):
            raise DomainError("COMPUTER_IMAGE_REQUIRED", 409)
        observed = await driver.resources.observation(scope, images[0]["observationId"])
        resource = await driver.resources.resource(scope, observed["resource_id"])
        if resource["kind"] != kind:
            raise DomainError("DESKTOP_RESOURCE_SCOPE_INVALID", 409)
        observation_id = observed["id"]
    else:
        observed = await driver.db.call(
            lambda db: row(
                db,
                "SELECT o.id FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                "JOIN resource_observations o ON o.id=json_extract(json_extract(native_content(m.content_json),'$.text'),'$.observation.id') "
                "JOIN resources r ON r.id=o.resource_id "
                "WHERE x.turn_id=? AND x.assistant_message_id!=? AND x.state='succeeded' "
                "AND o.task_id=? AND o.run_id=? AND r.owner_id=? AND r.kind=? "
                "AND (? IS NULL OR r.id=?) ORDER BY m.seq DESC LIMIT 1",
                (
                    binding["turnId"],
                    binding["assistantMessageId"],
                    scope["taskId"],
                    scope["runId"],
                    scope["owner"],
                    kind,
                    args.get("resourceId"),
                    args.get("resourceId"),
                ),
            )
        )
        if observed is None:
            raise DomainError("RESOURCE_OBSERVATION_NOT_FOUND", 404)
        observation_id = observed["id"]
    return {
        **{key: value for key, value in args.items() if key != "resourceId"},
        "observationId": observation_id,
    }
