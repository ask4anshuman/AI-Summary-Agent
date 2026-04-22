from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        return {}

    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


def get_nested_config_value(config: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    if not dotted_path:
        return default

    current: Any = config
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    return current
