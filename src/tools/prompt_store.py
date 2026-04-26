# Purpose : Prompt registry for LLM interactions. Loads prompt templates from YAML
#           and resolves prompts by prompt set + prompt key. Supports repo-specific
#           prompt overrides stored in agent.yml repos[full_name].prompts.
# Called by: src/tools/llm_tools.py.

from typing import Any

from src.config import settings
from src.tools.config_loader import load_yaml_config


class PromptStore:
    def __init__(self, prompts_file: str | None = None, repo_prompts: dict[str, Any] | None = None) -> None:
        self._prompts_file = prompts_file or settings.prompts_file
        self._cache: dict[str, Any] | None = None
        self._repo_prompts = repo_prompts or {}  # Custom prompts for this repo

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = load_yaml_config(self._prompts_file)
        return self._cache

    def get_prompt(self, prompt_set: str, prompt_key: str) -> dict[str, str]:
        """Resolve prompt: check repo-specific first, then defaults from config/prompts.yml"""
        selected = (prompt_set or "default").strip()
        
        # Check repo-specific prompts first
        if selected in self._repo_prompts:
            repo_set = self._repo_prompts[selected]
            if isinstance(repo_set, dict) and prompt_key in repo_set:
                prompt_data = repo_set[prompt_key]
                if isinstance(prompt_data, dict):
                    system = str(prompt_data.get("system", "")).strip()
                    user = str(prompt_data.get("user", "")).strip()
                    if system and user:
                        return {"system": system, "user": user}
        
        # Fall back to default prompts from config/prompts.yml
        payload = self._load()
        prompt_sets = payload.get("prompt_sets", {}) if isinstance(payload, dict) else {}
        if not isinstance(prompt_sets, dict):
            raise ValueError("Invalid prompts.yml format: prompt_sets must be a mapping")

        selected_map = prompt_sets.get(selected)
        if not isinstance(selected_map, dict):
            raise ValueError(f"Prompt set not found: {selected} (not in repo-specific or default prompts)")

        prompt_data = selected_map.get(prompt_key)
        if not isinstance(prompt_data, dict):
            raise ValueError(f"Prompt key '{prompt_key}' not found in prompt set '{selected}'")

        system = str(prompt_data.get("system", "")).strip()
        user = str(prompt_data.get("user", "")).strip()
        if not system or not user:
            raise ValueError(f"Prompt '{selected}.{prompt_key}' must include non-empty system and user templates")

        return {"system": system, "user": user}
