# Purpose : Documentation suggestion agent. Uses the LLM to produce a list of recommended
#           documentation updates and a rationale based on the SQL diff and summary.
#           LLM output is required; no rule-based fallback is returned.
# Called by: src/agents/orchestrator.py (SQLDocumentationOrchestrator.run).

from src.tools.llm_tools import LLMClient


class DocumentationSuggesterAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def suggest_updates(self, sql_diff: str, summary: str, change_type: str, affected_objects: list[str]) -> dict:
        _ = change_type, affected_objects
        response = self.llm_client.suggest_doc_updates(sql_diff=sql_diff, summary=summary)

        return {
            "suggested_doc_updates": [str(item) for item in response.suggested_doc_updates],
            "rationale": str(response.rationale),
        }
