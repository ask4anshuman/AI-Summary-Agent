import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.config import settings
from src.tools.llm_tools import (
    LLMClient,
    PRCommentSummaryOutput,
    PublishOutput,
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    object.__setattr__(settings, "openai_api_key", "test-key")
    object.__setattr__(settings, "openai_model", "gpt-4o-mini")
    object.__setattr__(settings, "openai_prompt_set", "ask4anshuman-agentic-sql-repo")

    monkeypatch.setattr(
        LLMClient,
        "generate_pr_comment_summary",
        lambda self, **kwargs: PRCommentSummaryOutput(
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
