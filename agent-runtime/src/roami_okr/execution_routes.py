"""Authenticated project Main execution configuration."""

from typing import Annotated, Literal

from fastapi import Header
from pydantic import Field

from roami_agent.protocol.http import Payload
from roami_okr.main_execution import main_configuration

Owner = Annotated[str, Header(alias="X-Roami-Owner", min_length=1, max_length=200)]


class MainExecution(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    projectId: str = Field(min_length=1, max_length=200)
    expectedGeneration: int = Field(ge=0)
    executor: Literal["claude", "codex"]
    model: str = Field(min_length=1, max_length=300)
    preparedLaunchKey: str = Field(min_length=1, max_length=200)
    recoverFromLaunchKey: str | None = Field(default=None, min_length=1, max_length=200)
    recoverProviderFromLaunchKey: str | None = Field(default=None, min_length=1, max_length=200)


class MainModelSelection(Payload):
    commandKey: str = Field(min_length=1, max_length=200)
    projectId: str = Field(min_length=1, max_length=200)
    expectedGeneration: int = Field(ge=1)
    expectedModel: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)


def mount_main_execution_routes(app, runtime):
    @app.get("/v1/conversations/{cid}/execution")
    async def configuration(cid: str, owner: Owner):
        return {"data": await runtime.db.call(lambda db: main_configuration(db, owner, cid))}

    @app.put("/v1/conversations/{cid}/execution")
    async def configure(cid: str, body: MainExecution, owner: Owner):
        return {
            "data": await runtime.main_executions.configure(
                owner, cid, body.model_dump(exclude_unset=True)
            )
        }

    @app.post("/v1/conversations/{cid}/execution/model", status_code=202)
    async def select_model(cid: str, body: MainModelSelection, owner: Owner):
        return {"data": await runtime.main_model_selections.request(owner, cid, body.model_dump())}
