from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversation(Payload):
    requestKey: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="New conversation", max_length=200)


class SendMessage(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=100_000)
    attachmentIds: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=6
    )


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
    goal: str = Field(min_length=1)
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


class SessionQuestionOption(Payload):
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=300)


class SessionQuestion(Payload):
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[SessionQuestionOption] = Field(min_length=2, max_length=4)


class SessionReport(Payload):
    key: str = Field(min_length=1, max_length=200)
    status: Literal["progress", "blocked", "completed", "failed"]
    summary: str = Field(min_length=1, max_length=8000)
    question: SessionQuestion | None = None

    @model_validator(mode="after")
    def valid_report(self):
        if not self.key.strip() or not self.summary.strip():
            raise ValueError("empty report")
        if self.question:
            labels = [o.label.strip() for o in self.question.options]
            if (
                self.status != "blocked"
                or not self.question.prompt.strip()
                or any(not label for label in labels)
                or len(set(labels)) != len(labels)
            ):
                raise ValueError("invalid report question")
        return self


class Confirm(Payload):
    accepted: bool


class ConfirmTask(Confirm):
    revision: int | None = Field(default=None, ge=1)
    runId: str | None = Field(default=None, min_length=1, max_length=200)


class SaveMemory(Payload):
    title: str = Field(max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    sourceMessageId: str
    kind: Literal["fact", "decision", "preference", "summary"] = "fact"
    projectId: str | None = None
    conversationId: str | None = None
    taskId: str | None = None
    dayKey: str | None = None


class SteerTask(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    text: str = Field(min_length=1)


class CreateReminder(Payload):
    requestKey: str = Field(min_length=1, max_length=200)
    conversationId: str
    text: str = Field(min_length=1)
    whenMs: int | None = Field(default=None, ge=0, le=8_000_000_000_000, strict=True)
    afterSeconds: int | None = Field(default=None, ge=1, le=2_678_400, strict=True)
    dailyAt: str | None = Field(default=None, min_length=5, max_length=5)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    kind: Literal["reminder", "daily_brief"] = "reminder"


class NotificationPreferences(Payload):
    settings: dict


class DeliveryReceipt(Payload):
    claimToken: str = Field(min_length=1, max_length=200)
    outcome: dict
