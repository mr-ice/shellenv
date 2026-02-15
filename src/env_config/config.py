"""Configuration helpers for env-config (global and user).

This module provides loading and saving of a global config (system-wide)
and a per-user config file. It exposes `load_merged_config` which merges
global and user configs with user settings taking precedence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GLOBAL_CONFIG_PATH = Path("/etc/env-config.json")


def user_config_path() -> Path:
    """Return the path to the user config file."""
    return Path.home() / ".env-config.json"


def load_config(path: Path) -> dict[str, Any]:
    """Load a config file and return its contents as a dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except Exception:
        return {}


def save_config(path: Path, data: dict[str, Any]) -> None:
    """Save a config dict to a file as JSON."""
    path.write_text(json.dumps(data, indent=2), encoding="utf8")


def load_merged_config() -> dict[str, Any]:
    """Load global and user configs and return merged view.

    User config values override global values. Missing files return an
    empty dict.
    """
    cfg: dict[str, Any] = {}
    try:
        if GLOBAL_CONFIG_PATH.exists():
            cfg = load_config(GLOBAL_CONFIG_PATH)
    except Exception:
        cfg = {}

    try:
        u = user_config_path()
        if u.exists():
            user_cfg = load_config(u)
            # shallow merge
            for k, v in user_cfg.items():
                cfg[k] = v
    except Exception:
        pass

    # ensure trace and tui default structures
    if "trace" not in cfg:
        cfg["trace"] = {"threshold_secs": None, "threshold_percent": None}
    else:
        cfg["trace"].setdefault("threshold_secs", None)
        cfg["trace"].setdefault("threshold_percent", None)

    if "tui" not in cfg:
        cfg["tui"] = {"page_size": 20}
    else:
        cfg["tui"].setdefault("page_size", 20)

    return cfg
