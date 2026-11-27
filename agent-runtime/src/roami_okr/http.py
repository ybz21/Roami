"""Project conversation routes and compatibility for Roami's public gateway."""

from pydantic import Field

from roami_agent.protocol.http import CreateConversation, Payload, SendMessage
from roami_agent.server.http import Owner
from roami_agent.server.http import create_app as create_agent_app
from roami_okr.daily_routes import mount_daily_routes
from roami_okr.execution_routes import mount_main_execution_routes
from roami_okr.intake import submit, wake_project
from roami_okr.main import open_main
from roami_okr.message_content import OKR_MESSAGE_CONTENT
from roami_okr.project import operation, registered_project


class CreateProjectConversation(CreateConversation):
    projectId: str | None = Field(default=None, min_length=1, max_length=200)


class SendProjectMessage(SendMessage):
    okrContext: dict | None = None


class WakeProject(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    projectId: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10_000)


def mount_project_conversations(app, runtime):
    mount_main_execution_routes(app, runtime)
    mount_daily_routes(app, runtime)

    @app.post("/v1/conversations", status_code=201)
    async def create_conversation(body: CreateProjectConversation, owner: Owner):
        conversations = runtime.conversations
        if body.projectId is None:
            return {
                "data": await conversations.create(owner, body.title, request_key=body.requestKey)
            }
        project_id = await registered_project(runtime.settings, body.projectId)
        workspace = await operation(runtime.settings, project_id, "show")
        await conversations.main(owner)
        return {
            "data": await open_main(
                conversations,
                owner,
                project_id,
                body.title,
                request_key=body.requestKey,
                swarm_id=workspace.get("swarm") if workspace else None,
            )
        }

    @app.post("/v1/conversations/{cid}/messages", status_code=202)
    async def send(cid: str, body: SendProjectMessage, owner: Owner):
        return {
            "data": await submit(
                runtime.chat,
                owner,
                cid,
                body.requestKey,
                body.text,
                body.attachmentIds,
                okr_context=body.okrContext,
            )
        }

    @app.post("/v1/conversations/{cid}/wake", status_code=202)
    async def wake(cid: str, body: WakeProject, owner: Owner):
        return {
            "data": await wake_project(
                runtime.chat, owner, cid, body.projectId, body.requestKey, body.text
            )
        }


def create_app(runtime, *, manage_lifecycle=True):
    runtime.db.message_content = OKR_MESSAGE_CONTENT
    return create_agent_app(
        runtime,
        manage_lifecycle=manage_lifecycle,
        mount_conversation_intake=mount_project_conversations,
    )
