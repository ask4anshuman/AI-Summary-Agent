# Purpose : Pydantic data models shared across the application — API request/response schemas,
#           agent result structures, and repo registration models.
# Called by: src/api/routes.py (request validation, response serialisation),
#            src/agents/orchestrator.py (AgentResult), src/tools/git_tools.py (GithubPRSQLFileChange).

from typing import Any

from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    """Request payload for local SQL summarize endpoint."""

    sql: str = Field(default="", description="SQL text for local summarize testing")
    source: str = Field(default="manual", description="Source of request")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Normalized orchestrator result returned by summarize flows."""

    summary: str
    markdown: str


class SummarizeResponse(BaseModel):
    """Response payload for summarize endpoint."""

    ok: bool = True
    result: AgentResult


class WebhookResponse(BaseModel):
    """Generic webhook/API operation response."""

    ok: bool
    message: str
    markdown: str = ""


class PRFileDocPayload(BaseModel):
    """Per-file PR comment payload captured for later publish steps."""

    filename: str
    summary: str
    markdown: str


class PublishedSQLDocPayload(BaseModel):
    """Structured documentation payload used for Confluence page content."""

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
    """Maps SQL path prefixes to Confluence parent page IDs."""

    sql_path_prefix: str
    parent_page_id: str


class RepoGithubConfig(BaseModel):
    """Repository-level GitHub integration settings."""

    owner: str
    name: str
    token: str = ""
    api_base_url: str = "https://api.github.com"
    webhook_secret: str = ""
    approval_command: str = "/approve-sql-doc"
    approval_label: str = "sql-doc-approved"


class RepoLlmConfig(BaseModel):
    """Repository-level LLM settings for model and prompt behavior."""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.1
    pr_summary_max_chars: int = 280
    prompt_set: str = ""


class RepoConfluenceConfig(BaseModel):
    """Repository-level Confluence connection and parent mapping settings."""

    base_url: str
    space: str
    username: str
    api_token: str
    default_parent_page_id: str = ""
    path_mappings: list[RepoPathMapping] = Field(default_factory=list)


class RepoPromptSet(BaseModel):
    """Custom prompt set with system and user templates for pr_comment and publish."""

    system_context: str = ""
    pr_comment: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})
    publish: dict[str, str] = Field(default_factory=lambda: {"system": "", "user": ""})


class RepoRegistrationRequest(BaseModel):
    """Request payload to register or update a repository configuration."""

    github: RepoGithubConfig
    llm: RepoLlmConfig = Field(default_factory=RepoLlmConfig)
    confluence: RepoConfluenceConfig
    prompts: dict[str, RepoPromptSet] | None = Field(default=None, description="Custom prompt sets (optional). Key is prompt_set name, value is RepoPromptSet.")


class RepoRegistrationResponse(BaseModel):
    """Response payload returned after repository registration operations."""

    ok: bool
    message: str
    repo: str
