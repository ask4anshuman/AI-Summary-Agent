# Purpose : Prompt registry for LLM interactions. Loads prompt templates from YAML
#           and resolves prompts by prompt set + prompt key.
# Called by: src/tools/llm_tools.py.

from typing import Any

from src.config import settings
from src.tools.config_loader import load_yaml_config


class PromptStore:
    def __init__(self, prompts_file: str | None = None) -> None:
        self._prompts_file = prompts_file or settings.prompts_file
        self._cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            self._cache = load_yaml_config(self._prompts_file)
        return self._cache

    def get_prompt(self, prompt_set: str, prompt_key: str) -> dict[str, str]:
        payload = self._load()
        prompt_sets = payload.get("prompt_sets", {}) if isinstance(payload, dict) else {}
        if not isinstance(prompt_sets, dict):
            raise ValueError("Invalid prompts.yml format: prompt_sets must be a mapping")

        selected = prompt_set.strip() or "default"
        selected_map = prompt_sets.get(selected)
        if not isinstance(selected_map, dict):
            raise ValueError(f"Prompt set not found: {selected}")

        prompt_data = selected_map.get(prompt_key)
        if not isinstance(prompt_data, dict):
            raise ValueError(f"Prompt key '{prompt_key}' not found in prompt set '{selected}'")

        system = str(prompt_data.get("system", "")).strip()
        user = str(prompt_data.get("user", "")).strip()
        if not system or not user:
            raise ValueError(f"Prompt '{selected}.{prompt_key}' must include non-empty system and user templates")

        return {"system": system, "user": user}
