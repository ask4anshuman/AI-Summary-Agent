import json
from textwrap import dedent

from openai import OpenAI

from src.config import settings


def _normalize_openai_base_url(base_url: str) -> str | None:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        return None

    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]

    return cleaned or None


class LLMClient:
    def __init__(self) -> None:
        self._enabled = bool(settings.openai_api_key)
        self._client = (
            OpenAI(
                api_key=settings.openai_api_key,
                base_url=_normalize_openai_base_url(settings.openai_base_url),
            )
            if self._enabled
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def request_json(self, prompt: str, fallback: dict, temperature: float = 0.1) -> dict:
        if not self._enabled or self._client is None:
            return fallback

        effective_temperature = temperature if temperature != 0.1 else settings.openai_temperature

        try:
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                temperature=effective_temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a careful SQL analysis assistant."},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception:
            return fallback

        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return fallback


def build_summary_prompt(sql_diff: str, change_type: str, affected_objects: list[str]) -> str:
    return dedent(
        f"""
        Analyze this SQL/PLSQL change and return JSON only with keys:
        summary, change_type, impact_level

        Rules:
        - summary: 2-3 sentences for a mixed technical/business audience
        - change_type: short label
        - impact_level: low|medium|high

        Detected change type: {change_type}
        Affected objects: {", ".join(affected_objects) if affected_objects else "None detected"}

        SQL Diff:
        {sql_diff}
        """
    ).strip()


def build_doc_prompt(sql_diff: str, summary: str) -> str:
    return dedent(
        f"""
        Based on this SQL/PLSQL change and summary, return JSON only with keys:
        suggested_doc_updates (array of strings), rationale

        Guidelines:
        - Suggest documentation sections that should be updated
        - Keep suggestions practical and concrete

        Summary:
        {summary}

        SQL Diff:
        {sql_diff}
        """
    ).strip()


def build_publish_doc_prompt(sql_text: str, change_type: str, affected_objects: list[str]) -> str:
    return dedent(
        f"""
        Analyze this final merged SQL/PLSQL file and return JSON only with keys:
        full_summary, sql_description, object_types, table_details, join_details, filter_details, affected_objects

        Rules:
        - full_summary: 1-2 detailed paragraphs explaining the complete purpose and behavior of the SQL file
        - sql_description: detailed technical explanation covering objects, joins, filters, and business effect
        - object_types: array of object type labels such as TABLE, FUNCTION, PROCEDURE, TRIGGER, VIEW, DML
        - table_details: array of tables or primary objects referenced in the SQL file
        - join_details: array of notable joins with conditions when present
        - filter_details: array of WHERE/HAVING filters or other important filtering rules
        - affected_objects: array of impacted database objects

        Detected change type: {change_type}
        Detected affected objects: {", ".join(affected_objects) if affected_objects else "None detected"}

        Final SQL File Content:
        {sql_text}
        """
    ).strip()
