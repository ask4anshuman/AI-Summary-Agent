# Purpose : Central settings loader. Reads config/agent.yml and environment variables (.env),
#           merges them into a frozen Settings dataclass, and exposes a global `settings` singleton.
#           If no top-level llm/github/confluence sections exist in the YAML, it auto-promotes
#           the first registered repo's config as the global fallback.
# Called by: src/api/routes.py (settings singleton), src/tools/llm_tools.py (API key / model),
#            src/tools/confluence_tools.py (Confluence credentials).

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from src.tools.config_loader import get_nested_config_value, load_yaml_config

load_dotenv()


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip().strip('"').strip("'")


def _normalize_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_app_config_file = _get_env("APP_CONFIG_FILE", "config/agent.yml")
_yaml_config = load_yaml_config(_app_config_file)

# If no top-level llm/github/confluence sections exist, promote the first registered
# repo's config as global fallback so Settings resolves from repos: entries.
_repos_raw = _yaml_config.get("repos", {})
if isinstance(_repos_raw, dict) and _repos_raw:
    _first_repo: dict[str, Any] = next(iter(_repos_raw.values()), {})
    if isinstance(_first_repo, dict):
        if "llm" in _first_repo and "llm" not in _yaml_config:
            _yaml_config["llm"] = _first_repo["llm"]
        if "github" in _first_repo and "github" not in _yaml_config:
            _gh = _first_repo["github"]
            _yaml_config["github"] = {
                "api_base_url": _gh.get("api_base_url", "https://api.github.com"),
                "token": _gh.get("token", ""),
                "webhook_secret": _gh.get("webhook_secret", ""),
                "approval": {
                    "command": _gh.get("approval_command", "/approve-sql-doc"),
                    "label": _gh.get("approval_label", "sql-doc-approved"),
                    "state_file": _gh.get("approval_state_file", ".ai_sql_agent/approval_state.json"),
                },
            }
        if "confluence" in _first_repo and "confluence" not in _yaml_config:
            _cf = _first_repo["confluence"]
            _yaml_config["confluence"] = {
                "base_url": _cf.get("base_url", ""),
                "space": _cf.get("space", ""),
                "parent_page_id": _cf.get("default_parent_page_id", ""),
                "username": _cf.get("username", ""),
                "api_token": _cf.get("api_token", ""),
            }


def _get_setting_str(env_name: str, yaml_path: str, default: str = "") -> str:
    env_value = _get_env(env_name, "")
    if env_value:
        return env_value
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, default)
    return _normalize_str(yaml_value, default)


def _get_setting_int(env_name: str, yaml_path: str, default: int) -> int:
    env_value = _get_env(env_name, "")
    if env_value:
        return _as_int(env_value, default)
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, default)
    return _as_int(yaml_value, default)


def _get_setting_float(env_name: str, yaml_path: str, default: float) -> float:
    env_value = _get_env(env_name, "")
    if env_value:
        return _as_float(env_value, default)
    yaml_value = get_nested_config_value(_yaml_config, yaml_path, default)
    return _as_float(yaml_value, default)


@dataclass(frozen=True)
class Settings:
    app_config_file: str = _app_config_file

    openai_api_key: str = _get_setting_str("OPENAI_API_KEY", "llm.api_key", "")
    openai_base_url: str = _get_setting_str("OPENAI_BASE_URL", "llm.base_url", "")
    openai_model: str = _get_setting_str("OPENAI_MODEL", "llm.model", "gpt-4o-mini")
    openai_temperature: float = _get_setting_float("OPENAI_TEMPERATURE", "llm.temperature", 0.1)
    pr_summary_max_chars: int = _get_setting_int("PR_SUMMARY_MAX_CHARS", "llm.pr_summary_max_chars", 280)
    openai_prompt_set: str = _get_setting_str("OPENAI_PROMPT_SET", "llm.prompt_set", "default")

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

    bitbucket_api_base_url: str = _get_setting_str("BITBUCKET_API_BASE_URL", "bitbucket.api_base_url", "")
    bitbucket_token: str = _get_setting_str("BITBUCKET_TOKEN", "bitbucket.token", "")

    confluence_base_url: str = _get_setting_str("CONFLUENCE_BASE_URL", "confluence.base_url", "")
    confluence_space: str = _get_setting_str("CONFLUENCE_SPACE", "confluence.space", "")
    confluence_parent_page_id: str = _get_setting_str("CONFLUENCE_PARENT_PAGE_ID", "confluence.parent_page_id", "")
    confluence_username: str = _get_setting_str("CONFLUENCE_USERNAME", "confluence.username", "")
    confluence_api_token: str = _get_setting_str("CONFLUENCE_API_TOKEN", "confluence.api_token", "")

    app_host: str = _get_setting_str("APP_HOST", "app.host", "0.0.0.0")
    app_port: int = _get_setting_int("APP_PORT", "app.port", 8000)
    repo_registry_file: str = _get_setting_str("REPO_REGISTRY_FILE", "app.repo_registry_file", "config/agent.yml")
    prompts_file: str = _get_setting_str("PROMPTS_FILE", "app.prompts_file", "config/prompts.yml")


settings = Settings()
