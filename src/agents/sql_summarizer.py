from src.tools.llm_tools import LLMClient, build_summary_prompt
from src.tools.sql_parser import analyze_operation_mix, detect_change_type, estimate_impact_level, extract_affected_objects


class SQLSummarizerAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def summarize(self, sql_diff: str, sql_for_analysis: str) -> dict:
        change_type = detect_change_type(sql_for_analysis)
        affected_objects = extract_affected_objects(sql_for_analysis)
        estimated_impact = estimate_impact_level(sql_for_analysis, affected_objects)

        op_mix = analyze_operation_mix(sql_for_analysis)
        fallback_summary = self._build_fallback_summary(change_type, affected_objects, op_mix)
        fallback = {
            "summary": fallback_summary,
            "change_type": change_type,
            "impact_level": estimated_impact,
        }

        prompt = build_summary_prompt(sql_diff=sql_diff, change_type=change_type, affected_objects=affected_objects)
        response = self.llm_client.request_json(prompt=prompt, fallback=fallback)

        return {
            "summary": response.get("summary", fallback_summary),
            "change_type": response.get("change_type", change_type),
            "impact_level": response.get("impact_level", estimated_impact),
            "affected_objects": affected_objects,
        }

    def _build_fallback_summary(self, change_type: str, affected_objects: list[str], op_mix: dict[str, int]) -> str:
        objects = ", ".join(affected_objects[:5]) if affected_objects else "no specific database objects"
        operations = ", ".join(f"{name}:{count}" for name, count in sorted(op_mix.items())) or "no clear SQL verbs"
        return (
            f"The SQL change is classified as {change_type} and touches {objects}. "
            f"Observed operation mix is {operations}. "
            "Review downstream documents and data contracts for consistency before release."
        )
