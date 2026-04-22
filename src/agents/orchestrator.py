from src.agents.doc_suggester import DocumentationSuggesterAgent
from src.agents.sql_summarizer import SQLSummarizerAgent
from src.models import AgentResult
from src.tools.git_tools import generate_unified_diff, parse_sql_diff
from src.tools.llm_tools import LLMClient
from src.tools.sql_parser import basic_sql_sanity_checks


class SQLDocumentationOrchestrator:
    def __init__(self) -> None:
        llm_client = LLMClient()
        self.summarizer = SQLSummarizerAgent(llm_client=llm_client)
        self.doc_suggester = DocumentationSuggesterAgent(llm_client=llm_client)

    def run(self, previous_sql: str = "", current_sql: str = "", diff: str = "") -> AgentResult:
        working_diff = diff.strip() if diff.strip() else generate_unified_diff(previous_sql, current_sql)

        diff_parts = parse_sql_diff(working_diff)
        analysis_sql = "\n".join(diff_parts["added"] + diff_parts["removed"]).strip()
        if not analysis_sql:
            analysis_sql = current_sql or previous_sql

        summary_result = self.summarizer.summarize(sql_diff=working_diff, sql_for_analysis=analysis_sql)
        doc_result = self.doc_suggester.suggest_updates(
            sql_diff=working_diff,
            summary=summary_result["summary"],
            change_type=summary_result["change_type"],
            affected_objects=summary_result["affected_objects"],
        )

        sanity_warnings = basic_sql_sanity_checks(analysis_sql)
        markdown = self._format_markdown(summary_result, doc_result, sanity_warnings)

        return AgentResult(
            summary=summary_result["summary"],
            change_type=summary_result["change_type"],
            impact_level=summary_result["impact_level"],
            affected_objects=summary_result["affected_objects"],
            suggested_doc_updates=doc_result["suggested_doc_updates"],
            rationale=doc_result["rationale"],
            markdown=markdown,
        )

    def _format_markdown(self, summary_result: dict, doc_result: dict, sanity_warnings: list[str]) -> str:
        object_lines = "\n".join(f"- {name}" for name in summary_result["affected_objects"]) or "- None detected"
        doc_lines = "\n".join(f"- {item}" for item in doc_result["suggested_doc_updates"])
        warning_lines = "\n".join(f"- {item}" for item in sanity_warnings) if sanity_warnings else "- No obvious syntax warnings"

        return (
            "## SQL Change Summary\n"
            f"- **Change Type:** {summary_result['change_type']}\n"
            f"- **Impact Level:** {summary_result['impact_level']}\n\n"
            f"{summary_result['summary']}\n\n"
            "## Affected Objects\n"
            f"{object_lines}\n\n"
            "## Suggested Documentation Updates\n"
            f"{doc_lines}\n\n"
            "## Rationale\n"
            f"{doc_result['rationale']}\n\n"
            "## SQL Sanity Checks\n"
            f"{warning_lines}\n"
        )
