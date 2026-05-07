# Purpose : Central settings loader. Reads config/registered_repos.yml and environment variables (.env),
#           merges them into a frozen Settings dataclass, and exposes a global `settings` singleton.
#           It does not auto-promote repo config into global sections.
# Called by: src/api/routes.py (settings singleton), src/tools/llm_tools.py (API key / model),
#            src/tools/confluence_tools.py (Confluence credentials).

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from src.tools.config_loader import get_nested_config_value, load_yaml_config

load_dotenv()


def _get_env(name: str, fallback: str = "") -> str:
    value = os.getenv(name, fallback)
    return value.strip().strip('"').strip("'")


def _normalize_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip()


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _get_setting_str(env_name: str, yaml_path: str, fallback: str = "") -> str:
    env_value = _get_env(env_name, "")
    if env_value:
        return env_value
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, fallback)
    return _normalize_str(yaml_value, fallback)


def _get_setting_int(env_name: str, yaml_path: str, fallback: int) -> int:
    env_value = _get_env(env_name, "")
    if env_value:
        return _as_int(env_value, fallback)
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, fallback)
    return _as_int(yaml_value, fallback)


def _get_setting_float(env_name: str, yaml_path: str, fallback: float) -> float:
    env_value = _get_env(env_name, "")
    if env_value:
        return _as_float(env_value, fallback)
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, fallback)
    return _as_float(yaml_value, fallback)


_app_config_file = _get_env("APP_CONFIG_FILE", "config/registered_repos.yml")
_yaml_config = load_yaml_config(_app_config_file)


@dataclass(frozen=True)
class Settings:
    app_config_file: str = _app_config_file

    openai_api_key: str = _get_setting_str("OPENAI_API_KEY", "llm.api_key", "")
    openai_base_url: str = _get_setting_str("OPENAI_BASE_URL", "llm.base_url", "")
    openai_model: str = _get_setting_str("OPENAI_MODEL", "llm.model", "gpt-4o-mini")
    openai_temperature: float = _get_setting_float("OPENAI_TEMPERATURE", "llm.temperature", 0.1)
    pr_summary_max_chars: int = _get_setting_int("PR_SUMMARY_MAX_CHARS", "llm.pr_summary_max_chars", 280)
    openai_prompt_set: str = _get_setting_str("OPENAI_PROMPT_SET", "llm.prompt_set", "")

    github_api_base_url: str = _get_setting_str("GITHUB_API_BASE_URL", "github.api_base_url", "")
    github_token: str = _get_setting_str("GITHUB_TOKEN", "github.token", "")
    github_webhook_secret: str = _get_setting_str("GITHUB_WEBHOOK_SECRET", "github.webhook_secret", "")
    github_approval_command: str = _get_setting_str(
        "GITHUB_APPROVAL_COMMAND", "github.approval.command", "/approve-sql-doc"
    )
    github_approval_label: str = _get_setting_str(
        "GITHUB_APPROVAL_LABEL", "github.approval.label", "sql-doc-approved"
    )
    approval_state_file: str = _get_setting_str(
        "APPROVAL_STATE_FILE", "github.approval.state_file", ".ai_sql_agent/approval_state.json"
    )

    confluence_base_url: str = _get_setting_str("CONFLUENCE_BASE_URL", "confluence.base_url", "")
    confluence_space: str = _get_setting_str("CONFLUENCE_SPACE", "confluence.space", "")
    confluence_parent_page_id: str = _get_setting_str("CONFLUENCE_PARENT_PAGE_ID", "confluence.parent_page_id", "")
    confluence_username: str = _get_setting_str("CONFLUENCE_USERNAME", "confluence.username", "")
    confluence_api_token: str = _get_setting_str("CONFLUENCE_API_TOKEN", "confluence.api_token", "")

    app_host: str = _get_setting_str("APP_HOST", "app.host", "0.0.0.0")
    app_port: int = _get_setting_int("APP_PORT", "app.port", 8000)
    repo_registry_file: str = _get_setting_str("REPO_REGISTRY_FILE", "app.repo_registry_file", "config/registered_repos.yml")
    prompts_file: str = _get_setting_str("PROMPTS_FILE", "app.prompts_file", "config/prompts.yml")


settings = Settings()
