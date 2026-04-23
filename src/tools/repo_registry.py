import copy
import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.tools.config_loader import resolve_env_vars

# Sensitive fields that must never be written as plaintext to the YAML registry.
# Structure: { section_key: [field_names] }
_SECRET_FIELDS: dict[str, list[str]] = {
    "github": ["token", "webhook_secret"],
    "confluence": ["api_token"],
    "llm": ["api_key"],
}

_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _env_var_name(full_name: str, section: str, field: str) -> str:
    """Generate a deterministic, uppercased env var name from repo full_name + field path."""
    safe_repo = re.sub(r"[^A-Za-z0-9]", "_", full_name).upper()
    return f"{section.upper()}_{field.upper()}_{safe_repo}"


class RepoRegistryStore:
    def __init__(self, file_path: str, env_file: str = ".env") -> None:
        self._file_path = Path(file_path)
        self._env_file = Path(env_file)

    def _is_yaml(self) -> bool:
        return self._file_path.suffix.lower() in {".yml", ".yaml"}

    # ------------------------------------------------------------------
    # Secret handling
    # ------------------------------------------------------------------

    def _extract_secrets(self, full_name: str, config: dict[str, Any]) -> dict[str, Any]:
        """
        For each known secret field in config, if the value is a real secret
        (not already a ${...} reference), write it to .env and replace the
        value with a ${ENV_VAR_NAME} reference.  Returns the sanitised config.
        """
        config = copy.deepcopy(config)
        for section, fields in _SECRET_FIELDS.items():
            section_cfg = config.get(section)
            if not isinstance(section_cfg, dict):
                continue
            for field in fields:
                value = section_cfg.get(field, "")
                if not value or _ENV_REF_RE.match(str(value)):
                    continue  # already a reference or empty — leave as-is
                var_name = _env_var_name(full_name, section, field)
                self._write_env_var(var_name, str(value))
                # Make available in the current process without restart
                import os  # noqa: PLC0415
                os.environ[var_name] = str(value)
                section_cfg[field] = f"${{{var_name}}}"
        return config

    def _write_env_var(self, name: str, value: str) -> None:
        """Append or update a single variable in the .env file."""
        existing_lines: list[str] = []
        if self._env_file.exists():
            existing_lines = self._env_file.read_text(encoding="utf-8").splitlines()

        prefix = f"{name}="
        new_line = f'{name}="{value}"'
        updated = False
        for i, line in enumerate(existing_lines):
            if line.startswith(prefix):
                existing_lines[i] = new_line
                updated = True
                break
        if not updated:
            existing_lines.append(new_line)

        self._env_file.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_repo(self, full_name: str, config: dict[str, Any]) -> dict[str, Any]:
        safe_config = self._extract_secrets(full_name.lower(), config)
        data = self._read_all()
        repos = data.setdefault("repos", {})
        repos[full_name.lower()] = safe_config
        self._write_all(data)
        return safe_config

    def get_repo(self, full_name: str) -> dict[str, Any] | None:
        data = self._read_all()
        repos = data.get("repos", {})
        if not isinstance(repos, dict):
            return None
        value = repos.get(full_name.lower())
        if not isinstance(value, dict):
            return None
        return resolve_env_vars(value)

    def delete_repo(self, full_name: str) -> bool:
        data = self._read_all()
        repos = data.get("repos", {})
        if not isinstance(repos, dict):
            return False

        key = full_name.lower()
        if key not in repos:
            return False

        repos.pop(key, None)
        self._write_all(data)
        return True

    def list_repos(self) -> dict[str, dict[str, Any]]:
        data = self._read_all()
        repos = data.get("repos", {})
        if not isinstance(repos, dict):
            return {}
        return {str(k): v for k, v in repos.items() if isinstance(v, dict)}

    # ------------------------------------------------------------------
    # Internal read/write (operates on raw YAML/JSON — no env resolution)
    # ------------------------------------------------------------------

    def _read_all(self) -> dict[str, Any]:
        if not self._file_path.exists():
            return {"repos": {}}

        raw_text = self._file_path.read_text(encoding="utf-8")

        try:
            if self._is_yaml():
                payload = yaml.safe_load(raw_text)
            else:
                payload = json.loads(raw_text)
        except (json.JSONDecodeError, yaml.YAMLError):
            return {"repos": {}}

        if not isinstance(payload, dict):
            return {"repos": {}}

        if not isinstance(payload.get("repos"), dict):
            payload["repos"] = {}

        return payload

    def _write_all(self, payload: dict[str, Any]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        if self._is_yaml():
            self._file_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            return
        self._file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
