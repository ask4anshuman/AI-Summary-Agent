# Purpose : Agent orchestrator. Generates a unified diff, calls the LLM once for a concise
#           change summary (PR-comment style), and returns a single AgentResult.
# Called by: src/api/routes.py (_run_orchestrator, summarize_sql endpoint),
#            src/local_batch.py (process_sql_directory),
#            tests/test_orchestrator.py.

from src.models import AgentResult
from src.tools.git_tools import generate_unified_diff, parse_sql_diff
from src.tools.llm_tools import LLMClient


class SQLDocumentationOrchestrator:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def run(self, previous_sql: str = "", current_sql: str = "", diff: str = "") -> AgentResult:
        working_diff = diff.strip() if diff.strip() else generate_unified_diff(previous_sql, current_sql)

        diff_parts = parse_sql_diff(working_diff)
        analysis_sql = "\n".join(diff_parts["added"] + diff_parts["removed"]).strip()
        if not analysis_sql:
            analysis_sql = current_sql or previous_sql

        summary_response = self.llm_client.generate_pr_comment_summary(
            filename="manual.sql",
            status="modified",
            previous_filename="",
            sql_diff=working_diff,
        )

        markdown = self._format_markdown(summary_response.summary)

        return AgentResult(
            summary=summary_response.summary,
            markdown=markdown,
        )

    def _format_markdown(self, summary: str) -> str:
        return (
            "## SQL Change Summary\n"
            f"{summary}\n"
        )
