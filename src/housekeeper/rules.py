import os
from typing import Any

import yaml

DEFAULT_RULES_PATH = "/app/config/rules.yaml"


def _candidate_paths(explicit_path: str | None) -> list[str]:
    out: list[str] = []
    if explicit_path:
        out.append(explicit_path)
    out.extend(
        [
            "/config/ha_housekeeper/rules.yaml",
            "/config/ha_housekeeper_rules.yaml",
            DEFAULT_RULES_PATH,
        ]
    )
    # de-dup while preserving order
    seen = set()
    uniq = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    return uniq


def find_rules_path(explicit_path: str | None = None) -> str | None:
    for p in _candidate_paths(explicit_path):
        if p and os.path.exists(p):
            return p
    return None


def load_rules(explicit_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Returns (rules, meta).
    meta includes: path, error (optional)
    """
    path = find_rules_path(explicit_path)
    if not path:
        return {}, {"path": None, "error": "No rules file found"}

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}, {"path": path, "error": "Rules file root must be a mapping/object"}
        return data, {"path": path}
    except Exception as e:
        return {}, {"path": path, "error": str(e)}
