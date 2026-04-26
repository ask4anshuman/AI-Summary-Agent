# Purpose : Pydantic data models shared across the application — API request/response schemas,
#           agent result structures, and repo registration models.
# Called by: src/api/routes.py (request validation, response serialisation),
#            src/agents/orchestrator.py (AgentResult), src/tools/git_tools.py (GithubPRSQLFileChange).

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


class PublishedSQLDocPayload(BaseModel):
    filename: str
    full_summary: str
    sql_description: str
    object_types: list[str]
    table_details: list[str]
    join_details: list[str]
    filter_details: list[str]
    affected_objects: list[str]
    page_heading: str = ""


class RepoPathMapping(BaseModel):
    sql_path_prefix: str
    parent_page_id: str


class RepoGithubConfig(BaseModel):
    owner: str
    name: str
    token: str = ""
    api_base_url: str = "https://api.github.com"
    webhook_secret: str = ""
    approval_command: str = "/approve-sql-doc"
    approval_label: str = "sql-doc-approved"


class RepoLlmConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.1
    pr_summary_max_chars: int = 280
    prompt_set: str = "default"


class RepoConfluenceConfig(BaseModel):
    base_url: str
    space: str
    username: str
    api_token: str
    default_parent_page_id: str = ""
    path_mappings: list[RepoPathMapping] = Field(default_factory=list)


class RepoPromptSet(BaseModel):
    """Custom prompt set definition. Contains system and user templates for 4 LLM operations."""
    summary: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})
    doc_suggestion: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})
    pr_comment: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})
    publish: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})


class RepoRegistrationRequest(BaseModel):
    github: RepoGithubConfig
    llm: RepoLlmConfig = Field(default_factory=RepoLlmConfig)
    confluence: RepoConfluenceConfig
    prompts: dict[str, RepoPromptSet] | None = Field(default=None, description="Custom prompt sets (optional). Key is prompt_set name, value is RepoPromptSet.")


class RepoRegistrationResponse(BaseModel):
    ok: bool
    message: str
    repo: str
