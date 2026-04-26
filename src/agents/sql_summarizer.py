# Purpose : SQL summarisation agent. Uses the LLM to generate a natural-language summary,
#           change type, and impact level from a SQL diff.
#           Parser-derived signals are used as context hints for the LLM prompt.
# Called by: src/agents/orchestrator.py (SQLDocumentationOrchestrator.run).

from src.tools.llm_tools import LLMClient
from src.tools.sql_parser import detect_change_type, extract_affected_objects


class SQLSummarizerAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def summarize(self, sql_diff: str, sql_for_analysis: str) -> dict:
        change_type = detect_change_type(sql_for_analysis)
        affected_objects = extract_affected_objects(sql_for_analysis)
        response = self.llm_client.summarize_sql(
            sql_diff=sql_diff,
            change_type=change_type,
            affected_objects=affected_objects,
        )

        return {
            "summary": response.summary,
            "change_type": response.change_type,
            "impact_level": response.impact_level,
            "affected_objects": affected_objects,
        }
