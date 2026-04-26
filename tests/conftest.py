import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.config import settings
from src.tools.llm_tools import (
    DocSuggestionOutput,
    LLMClient,
    PRCommentOutput,
    PublishOutput,
    SummaryOutput,
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    object.__setattr__(settings, "openai_api_key", "test-key")
    object.__setattr__(settings, "openai_model", "gpt-4o-mini")
    object.__setattr__(settings, "openai_prompt_set", "default")

    monkeypatch.setattr(
        LLMClient,
        "summarize_sql",
        lambda self, **kwargs: SummaryOutput(
            summary="Mocked SQL summary",
            change_type=str(kwargs.get("change_type", "DML")) or "DML",
            impact_level="medium",
        ),
    )
    monkeypatch.setattr(
        LLMClient,
        "suggest_doc_updates",
        lambda self, **kwargs: DocSuggestionOutput(
            suggested_doc_updates=["Release Notes", "Data Dictionary"],
            rationale="Mocked rationale",
        ),
    )
    monkeypatch.setattr(
        LLMClient,
        "summarize_pr_change",
        lambda self, **kwargs: PRCommentOutput(
            summary="Mocked concise PR summary for SQL change.",
        ),
    )
    monkeypatch.setattr(
        LLMClient,
        "generate_publish_doc",
        lambda self, **kwargs: PublishOutput(
            full_summary="Mocked full summary for merged SQL.",
            sql_description="Mocked SQL description.",
            object_types=list(kwargs.get("object_types", [])),
            table_details=list(kwargs.get("table_details", [])),
            join_details=[],
            filter_details=[],
            affected_objects=list(kwargs.get("affected_objects", [])),
            page_heading="",
        ),
    )
