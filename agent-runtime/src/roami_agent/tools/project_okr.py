"""Project-scoped OKR tools for the goal's persistent coordinator."""

from roami_agent.conversation.project_main import project_team
from roami_agent.conversation.project_okr import bound_project, operation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


def register_project_okr_tools(registry, database, settings):
    async def context(args, binding):
        pid = await bound_project(database, binding)
        workspace = await operation(settings, pid, "show")
        return {**(workspace or {}), "projectId": pid, "saved": workspace is not None}

    async def update(args, binding):
        pid = await bound_project(database, binding)
        if args["operation"] == "save" and args["payload"].get("swarm"):
            team = await database.call(
                lambda db: project_team(db, binding["owner"], pid, args["payload"]["swarm"])
            )
            if team["conversation_id"] != binding["conversation"]:
                raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
        return await operation(settings, pid, args["operation"], args["payload"])

    registry.add(
        Tool(
            "project_okr_context",
            "Read this goal conversation's bound registered project OKR: current revision, definitions, dashboard, dated observations/reviews and project instructions/memory. A new goal returns saved=false without invented metrics. Project selection is fixed by the host and cannot be supplied by the model.",
            object_schema({}),
            context,
            effect="read",
            main=True,
        )
    )
    registry.add(
        Tool(
            "project_okr_update",
            "Apply a user-confirmed OKR change only to this goal conversation's bound project. First read project_okr_context; use its revision and the existing validated project operation JSON. Save objective, dashboard, Connector bindings and desired team roles (team.schemaVersion=1, roles with id/name/executor/duty); saving roles does not register or dispatch members. Collect registered sources, record real observations, review, sync staged definitions or update memory with expectedSha256. For whole-project creation discover okr-development. Conflicts require rereading. No shell, paths, credentials, model settings or public posting.",
            object_schema(
                {
                    "operation": {
                        "type": "string",
                        "enum": ["save", "collect", "record", "review", "sync", "memory"],
                    },
                    "payload": {"type": "object"},
                },
                ["operation", "payload"],
            ),
            update,
            effect="write",
            main=True,
        )
    )
