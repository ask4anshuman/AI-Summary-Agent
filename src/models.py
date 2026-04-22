from typing import Any

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    current_sql: str = Field(default="", description="Latest SQL text")
    previous_sql: str = Field(default="", description="Previous SQL text")
    diff: str = Field(default="", description="Optional precomputed unified diff")
    source: str = Field(default="manual", description="Source of request")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    summary: str
    change_type: str
    impact_level: str
    affected_objects: list[str]
    suggested_doc_updates: list[str]
    rationale: str
    markdown: str


class SummarizeResponse(BaseModel):
    ok: bool = True
    result: AgentResult


class WebhookResponse(BaseModel):
    ok: bool
    message: str
    markdown: str = ""


class PRFileDocPayload(BaseModel):
    filename: str
    summary: str
    markdown: str
    change_type: str
    impact_level: str
    affected_objects: list[str]
    suggested_doc_updates: list[str]
    rationale: str
