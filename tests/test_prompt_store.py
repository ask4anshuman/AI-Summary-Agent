from pydantic import BaseModel

from src.tools.llm_tools import LLMClient
from src.tools.prompt_store import PromptStore


class _SimpleOutput(BaseModel):
    summary: str


def test_prompt_store_returns_default_system_context() -> None:
    store = PromptStore(prompts_file="c:/Users/ANSHUMAN/AI-Summary-Agent/config/prompts.yml")

    prompt = store.get_prompt("ask4anshuman-agentic-sql-repo", "pr_comment")

    assert prompt["system_context"]
    assert "SQL documentation workflow" in prompt["system_context"]


def test_prompt_store_prefers_repo_system_context() -> None:
    store = PromptStore(
        repo_prompts={
            "ask4anshuman-agentic-sql-repo": {
                "system_context": "Repo-specific context",
                "pr_comment": {"system": "Repo system", "user": "Repo user"},
            }
        }
    )

    prompt = store.get_prompt("ask4anshuman-agentic-sql-repo", "pr_comment")

    assert prompt["system_context"] == "Repo-specific context"
    assert prompt["system"] == "Repo system"
    assert prompt["user"] == "Repo user"


def test_llm_client_includes_system_context_message(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        content = '{"summary": "ok"}'

    class _FakeChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def invoke(self, messages):
            captured["messages"] = messages
            return _FakeResponse()

    monkeypatch.setattr("src.tools.llm_tools.ChatOpenAI", _FakeChat)

    client = LLMClient(
        api_key="test-key",
        model="gpt-4o-mini",
        prompt_store=PromptStore(
            repo_prompts={
                "ask4anshuman-agentic-sql-repo": {
                    "system_context": "Shared context",
                    "pr_comment": {"system": "Task system", "user": "Summarize {filename}. {format_instructions}"},
                }
            }
        ),
    )

    result = client._invoke_structured(
        prompt_key="pr_comment",
        variables={"filename": "a.sql"},
        output_model=_SimpleOutput,
    )

    messages = captured["messages"]
    assert result.summary == "ok"
    assert len(messages) == 3
    assert messages[0].content == "Shared context"
    assert messages[1].content == "Task system"


def test_prompt_store_requires_explicit_prompt_set() -> None:
    store = PromptStore(prompts_file="c:/Users/ANSHUMAN/AI-Summary-Agent/config/prompts.yml")

    try:
        store.get_prompt("", "pr_comment")
    except ValueError as exc:
        assert "Prompt set is required" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected ValueError for missing prompt set")