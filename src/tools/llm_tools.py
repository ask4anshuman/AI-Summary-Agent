# Purpose : Strict LangChain-based LLM service. Resolves prompts from prompts.yml,
#           invokes ChatOpenAI, and parses structured JSON responses.
# Called by: src/agents/sql_summarizer.py, src/agents/doc_suggester.py, src/api/routes.py.

from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import settings
from src.tools.prompt_store import PromptStore


class LLMConfigurationError(RuntimeError):
    pass


class LLMInvocationError(RuntimeError):
    pass


class SummaryOutput(BaseModel):
    summary: str
    change_type: str
    impact_level: str


class DocSuggestionOutput(BaseModel):
    suggested_doc_updates: list[str]
    rationale: str


class PRCommentOutput(BaseModel):
    summary: str


class PublishOutput(BaseModel):
    full_summary: str
    sql_description: str
    object_types: list[str] = Field(default_factory=list)
    table_details: list[str] = Field(default_factory=list)
    join_details: list[str] = Field(default_factory=list)
    filter_details: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    page_heading: str = ""


def _normalize_openai_base_url(base_url: str) -> str | None:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        return None

    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]

    return cleaned or None


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        temperature: float | None = None,
        prompt_set: str = "",
        prompt_store: PromptStore | None = None,
    ) -> None:
        self.api_key = (api_key or settings.openai_api_key).strip()
        self.base_url = _normalize_openai_base_url(base_url or settings.openai_base_url)
        self.model = (model or settings.openai_model).strip()
        self.temperature = settings.openai_temperature if temperature is None else float(temperature)
        self.prompt_set = (prompt_set or settings.openai_prompt_set or "default").strip()
        self.prompt_store = prompt_store or PromptStore()

        if not self.api_key:
            raise LLMConfigurationError("LLM API key is required. Configure llm.api_key (or OPENAI_API_KEY).")
        if not self.model:
            raise LLMConfigurationError("LLM model is required. Configure llm.model (or OPENAI_MODEL).")

        self._chat = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
        )

    @property
    def enabled(self) -> bool:
        return True

    def summarize_sql(self, *, sql_diff: str, change_type: str, affected_objects: list[str]) -> SummaryOutput:
        return self._invoke_structured(
            prompt_key="summary",
            variables={
                "sql_diff": sql_diff,
                "change_type": change_type,
                "affected_objects": ", ".join(affected_objects) if affected_objects else "None detected",
            },
            output_model=SummaryOutput,
        )

    def suggest_doc_updates(self, *, sql_diff: str, summary: str) -> DocSuggestionOutput:
        return self._invoke_structured(
            prompt_key="doc_suggestion",
            variables={
                "sql_diff": sql_diff,
                "summary": summary,
            },
            output_model=DocSuggestionOutput,
        )

    def summarize_pr_change(
        self,
        *,
        filename: str,
        status: str,
        previous_filename: str,
        sql_diff: str,
    ) -> PRCommentOutput:
        return self._invoke_structured(
            prompt_key="pr_comment",
            variables={
                "filename": filename,
                "status": status,
                "previous_filename": previous_filename or "",
                "sql_diff": sql_diff,
            },
            output_model=PRCommentOutput,
        )

    def generate_publish_doc(
        self,
        *,
        sql_text: str,
        pr_summary: str,
        change_type: str,
        affected_objects: list[str],
        object_types: list[str],
        table_details: list[str],
    ) -> PublishOutput:
        return self._invoke_structured(
            prompt_key="publish",
            variables={
                "sql_text": sql_text,
                "pr_summary": pr_summary or "No PR-level summary available.",
                "change_type": change_type,
                "affected_objects": ", ".join(affected_objects) if affected_objects else "None detected",
                "object_types": ", ".join(object_types) if object_types else "UNKNOWN",
                "table_details": ", ".join(table_details) if table_details else "None detected",
            },
            output_model=PublishOutput,
        )

    def _invoke_structured(self, *, prompt_key: str, variables: dict[str, Any], output_model: type[BaseModel]) -> Any:
        parser = PydanticOutputParser(pydantic_object=output_model)
        prompt_cfg = self.prompt_store.get_prompt(self.prompt_set, prompt_key)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", prompt_cfg["system"]),
                ("user", prompt_cfg["user"]),
            ]
        )

        final_vars = {**variables, "format_instructions": parser.get_format_instructions()}

        try:
            messages = prompt.format_messages(**final_vars)
            response = self._chat.invoke(messages)
            content = str(getattr(response, "content", "") or "")
            parsed = parser.parse(content)
            return parsed
        except Exception as exc:  # pragma: no cover - exact provider errors vary
            raise LLMInvocationError(f"LLM invocation failed for prompt '{prompt_key}': {exc}") from exc
