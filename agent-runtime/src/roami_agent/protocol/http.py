from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversation(Payload):
    requestKey: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="New conversation", max_length=200)


class SendMessage(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


class Compact(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    focus: str = Field(default="", max_length=2000)


class ReadCursor(Payload):
    eventId: int = Field(ge=0)


class Fork(Payload):
    messageId: str


class CreateTask(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    conversationId: str
    goal: str = Field(min_length=1, max_length=20_000)
    executor: Literal["native", "codex", "claude"] = "native"
    target: dict | None = None
    fromMessageId: str | None = None
    parentTaskId: str | None = None


class Report(Payload):
    taskId: str
    runId: str
    revision: int = Field(ge=1)
    result: dict


class Proactive(Payload):
    conversationId: str
    text: str = Field(min_length=1, max_length=30_000)
    source: str = Field(min_length=1, max_length=100)
    dedupeKey: str = Field(min_length=1, max_length=200)
    priority: Literal["normal", "attention"] = "normal"


class Confirm(Payload):
    accepted: bool


class SaveMemory(Payload):
    title: str = Field(max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    sourceMessageId: str
    kind: Literal["fact", "decision", "preference", "summary"] = "fact"
    projectId: str | None = None
    conversationId: str | None = None
    taskId: str | None = None
    dayKey: str | None = None
