from src.tools.llm_tools import LLMClient, build_doc_prompt


class DocumentationSuggesterAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def suggest_updates(self, sql_diff: str, summary: str, change_type: str, affected_objects: list[str]) -> dict:
        fallback = self._fallback_suggestions(change_type=change_type, affected_objects=affected_objects)
        prompt = build_doc_prompt(sql_diff=sql_diff, summary=summary)
        response = self.llm_client.request_json(prompt=prompt, fallback=fallback)

        suggestions = response.get("suggested_doc_updates", fallback["suggested_doc_updates"])
        rationale = response.get("rationale", fallback["rationale"])

        if not isinstance(suggestions, list):
            suggestions = fallback["suggested_doc_updates"]

        return {
            "suggested_doc_updates": [str(item) for item in suggestions],
            "rationale": str(rationale),
        }

    def _fallback_suggestions(self, change_type: str, affected_objects: list[str]) -> dict:
        base_sections = [
            "Data Dictionary",
            "Schema Change Log",
            "Release Notes",
            "ETL/Reporting Impact Notes",
        ]

        if "PLSQL" in change_type:
            base_sections.append("Stored Procedure/Package Reference")
        if "DDL" in change_type:
            base_sections.append("ERD / Schema Diagram")
        if affected_objects:
            base_sections.append("Object-Level Runbook Entries")

        return {
            "suggested_doc_updates": base_sections,
            "rationale": (
                "These sections are likely affected by SQL object and behavior changes and should be aligned "
                "with the latest implementation."
            ),
        }
