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
        repo_prompts: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = (api_key or settings.openai_api_key).strip()
        self.base_url = _normalize_openai_base_url(base_url or settings.openai_base_url)
        self.model = (model or settings.openai_model).strip()
        self.temperature = settings.openai_temperature if temperature is None else float(temperature)
        self.prompt_set = (prompt_set or settings.openai_prompt_set).strip()
        self.prompt_store = prompt_store or PromptStore(repo_prompts=repo_prompts or {})

        if not self.api_key:
            raise LLMConfigurationError("LLM API key is required. Configure llm.api_key (or OPENAI_API_KEY).")
        if not self.model:
            raise LLMConfigurationError("LLM model is required. Configure llm.model (or OPENAI_MODEL).")
        if not self.prompt_set:
            raise LLMConfigurationError("LLM prompt set is required. Configure llm.prompt_set (or OPENAI_PROMPT_SET).")

        self._chat = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
        )

    @property
    def enabled(self) -> bool:
        return True

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
    ) -> PublishOutput:
        return self._invoke_structured(
            prompt_key="publish",
            variables={
                "sql_text": sql_text,
                "pr_summary": pr_summary or "No PR-level summary available.",
            },
            output_model=PublishOutput,
        )

    def _invoke_structured(self, *, prompt_key: str, variables: dict[str, Any], output_model: type[BaseModel]) -> Any:
        parser = PydanticOutputParser(pydantic_object=output_model)
        prompt_cfg = self.prompt_store.get_prompt(self.prompt_set, prompt_key)
        prompt_messages: list[tuple[str, str]] = []
        if prompt_cfg.get("system_context", "").strip():
            prompt_messages.append(("system", prompt_cfg["system_context"]))
        prompt_messages.extend(
            [
                ("system", prompt_cfg["system"]),
                ("user", prompt_cfg["user"]),
            ]
        )
        prompt = ChatPromptTemplate.from_messages(prompt_messages)

        final_vars = {**variables, "format_instructions": parser.get_format_instructions()}

        try:
            messages = prompt.format_messages(**final_vars)
            response = self._chat.invoke(messages)
            content = str(getattr(response, "content", "") or "")
            parsed = parser.parse(content)
            return parsed
        except Exception as exc:  # pragma: no cover - exact provider errors vary
            raise LLMInvocationError(f"LLM invocation failed for prompt '{prompt_key}': {exc}") from exc
