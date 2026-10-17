"""Model output contains proposals and source IDs; it cannot grant activation or scope."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    kind: Literal["fact", "decision", "preference", "summary"]
    sourceIds: list[str] = Field(min_length=1, max_length=16)


class MemoryProposals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[MemoryProposal] = Field(max_length=8)
