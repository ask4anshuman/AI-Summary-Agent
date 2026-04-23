import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def resolve_env_vars(obj: Any) -> Any:
    """Recursively replace ${VAR_NAME} strings with their environment variable values."""
    if isinstance(obj, dict):
        return {k: resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_vars(item) for item in obj]
    if isinstance(obj, str):
        m = _ENV_REF_RE.match(obj)
        if m:
            return os.environ.get(m.group(1), obj)
    return obj


def load_yaml_config(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        return {}

    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}

    if not isinstance(parsed, dict):
        return {}

    return resolve_env_vars(parsed)


def get_nested_config_value(config: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    if not dotted_path:
        return default

    current: Any = config
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    return current
