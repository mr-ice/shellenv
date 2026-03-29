"""Configuration helpers for shellenv (global and user).

This module provides loading and saving of a global config (system-wide)
and a per-user config file, a declarative schema of all known config keys,
type coercion/validation helpers, and high-level get/set/reset/show
operations.  Config files use the TOML format.

Public API
----------
CONFIG_SCHEMA : dict[str, ConfigKey]
    All recognised configuration keys with types, defaults, and descriptions.
load_merged_config()
    Load global + user config merged with schema defaults.
config_get(key)
    Return the merged value for a dotted key.
config_set(key, value)
    Set a value in the user config (validates key and type).
config_reset(key)
    Remove a key from the user config (reverts to global/default).
config_show()
    Return a flat mapping of every schema key to its merged value.
validate_config(data)
    Validate a raw dict against the schema; returns a list of errors.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

GLOBAL_CONFIG_PATH = Path("/etc/shellenv.toml")

_MISSING = object()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class ConfigKey:
    """Metadata for a single configuration key.

    Attributes
    ----------
    key : str
        Dotted path such as ``trace.threshold_secs``.
    value_type : str
        One of ``float``, ``int``, ``string``, ``float_or_null``,
        ``string_or_null``, ``list_of_strings``.
    default : Any
        Default value when neither global nor user config supplies one.
    description : str
        Human-readable description shown in ``config show`` output.
    merge_strategy : str
        ``"replace"`` (default) or ``"append"`` (user list extends global list).
    """

    key: str
    value_type: str
    default: Any
    description: str
    merge_strategy: str = "replace"


CONFIG_SCHEMA: dict[str, ConfigKey] = {
    "shellenv.tool_repo_path": ConfigKey(
        key="shellenv.tool_repo_path",
        value_type="string",
        default="~/.shellenv",
        description="Directory (under home) where the shellenv tool repository is cloned/updated",
    ),
    "trace.threshold_secs": ConfigKey(
        key="trace.threshold_secs",
        value_type="float_or_null",
        default=None,
        description="Flag files taking longer than N seconds",
    ),
    "trace.threshold_percent": ConfigKey(
        key="trace.threshold_percent",
        value_type="float_or_null",
        default=None,
        description="Flag files taking longer than N% of total",
    ),
    "repo.url": ConfigKey(
        key="repo.url",
        value_type="string_or_null",
        default=None,
        description="Git repo URL for shell init files",
    ),
    "repo.destination": ConfigKey(
        key="repo.destination",
        value_type="string_or_null",
        default=None,
        description="Local path to clone repo into",
    ),
    "compose.paths": ConfigKey(
        key="compose.paths",
        value_type="list_of_strings",
        default=[],
        description="Compose sources: git URLs, local git repos, or plain directories; see PROJECT.md",
        merge_strategy="append",
    ),
    "compose.allowed_path_kinds": ConfigKey(
        key="compose.allowed_path_kinds",
        value_type="list_of_strings",
        default=["repo", "directory"],
        description=(
            "Allowed kinds for [compose] paths entries: repo (URL or git worktree), "
            "directory (plain folder); see PROJECT.md"
        ),
        merge_strategy="replace",
    ),
    "compose.shell_rc_files": ConfigKey(
        key="compose.shell_rc_files",
        value_type="list_of_strings",
        default=[],
        description="RC file variants (e.g. zshrc, zshenv, zprofile)",
        merge_strategy="append",
    ),
    "compose.allow_dirty_or_off_main": ConfigKey(
        key="compose.allow_dirty_or_off_main",
        value_type="string",
        default="false",
        description=(
            "If true, scan compose sources even when not on main/master at a clean HEAD; "
            "if false, require main:HEAD (see SHELLENV_COMPOSE_ALLOW_DIRTY for dirty-on-main). "
            "Plain directories outside any git worktree are always scanned if allowed by "
            "allowed_path_kinds. Defaults to false."
        ),
    ),
}


def _migrate_compose_legacy_keys(data: dict[str, Any]) -> None:
    """Rename deprecated ``compose.allow_non_repo`` to ``allow_dirty_or_off_main`` (in place)."""
    c = data.get("compose")
    if not isinstance(c, dict) or "allow_non_repo" not in c:
        return
    if "allow_dirty_or_off_main" not in c:
        c["allow_dirty_or_off_main"] = c.pop("allow_non_repo")
    else:
        c.pop("allow_non_repo", None)


# ---------------------------------------------------------------------------
# Nested-dict helpers
# ---------------------------------------------------------------------------


def get_nested(data: dict, dotted_key: str) -> Any:
    """Return the value at *dotted_key* in a nested dict.

    Parameters
    ----------
    data : dict
        The nested mapping to search.
    dotted_key : str
        A dot-separated path, e.g. ``"trace.threshold_secs"``.

    Returns
    -------
    Any
        The value, or the module-level sentinel ``_MISSING`` if not found.
    """
    parts = dotted_key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def set_nested(data: dict, dotted_key: str, value: Any) -> None:
    """Set *value* at *dotted_key*, creating intermediate dicts as needed.

    Parameters
    ----------
    data : dict
        Target nested mapping (modified in place).
    dotted_key : str
        Dot-separated path.
    value : Any
        Value to store.
    """
    parts = dotted_key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def delete_nested(data: dict, dotted_key: str) -> bool:
    """Remove *dotted_key* from a nested dict.

    Empty parent dicts are cleaned up after deletion.

    Parameters
    ----------
    data : dict
        Target nested mapping (modified in place).
    dotted_key : str
        Dot-separated path.

    Returns
    -------
    bool
        True if the key existed and was removed.
    """
    parts = dotted_key.split(".")
    ancestors: list[tuple[dict, str]] = []
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        ancestors.append((current, part))
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    # clean up empty parents
    for parent, key in reversed(ancestors):
        if isinstance(parent[key], dict) and not parent[key]:
            del parent[key]
    return True


# ---------------------------------------------------------------------------
# Coercion and validation
# ---------------------------------------------------------------------------


def _coerce_float(raw: str) -> float:
    """Coerce a string to float, raising ValueError on failure."""
    try:
        return float(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"expected a float, got {raw!r}") from exc


def _coerce_int(raw: str) -> int:
    """Coerce a string to int, raising ValueError on failure."""
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"expected an integer, got {raw!r}") from exc


def _is_null_token(raw: str) -> bool:
    """Return True if *raw* represents a null/empty value."""
    return raw.lower() in ("null", "none", "")


_COERCERS: dict[str, Any] = {
    "float": _coerce_float,
    "int": _coerce_int,
    "string": str,
    "float_or_null": lambda raw: None if _is_null_token(raw) else _coerce_float(raw),
    "string_or_null": lambda raw: None if _is_null_token(raw) else str(raw),
    "list_of_strings": lambda raw: [s.strip() for s in raw.split(",") if s.strip()],
}


def coerce_value(raw: str, value_type: str) -> Any:
    """Parse a CLI string into the Python type expected by *value_type*.

    Parameters
    ----------
    raw : str
        Raw string from command-line input.
    value_type : str
        Schema type name (``float``, ``int``, ``string``, ``float_or_null``,
        ``string_or_null``, ``list_of_strings``).

    Returns
    -------
    Any
        The coerced Python value.

    Raises
    ------
    ValueError
        If the string cannot be converted to the expected type.
    """
    coercer = _COERCERS.get(value_type)
    if coercer is None:
        raise ValueError(f"unknown value_type {value_type!r}")
    return coercer(raw)


def validate_value(value: Any, value_type: str) -> bool:
    """Check whether *value* matches the expected *value_type*.

    Parameters
    ----------
    value : Any
        A Python object (not a raw string).
    value_type : str
        Schema type name.

    Returns
    -------
    bool
        True if the value is acceptable for the type.
    """
    if value_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: UP038
    if value_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "float_or_null":
        if value is None:
            return True
        return isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: UP038
    if value_type == "string_or_null":
        return value is None or isinstance(value, str)
    if value_type == "list_of_strings":
        return isinstance(value, list) and all(isinstance(s, str) for s in value)
    return False


def _known_sections() -> set[str]:
    """Return the set of top-level section names derived from the schema."""
    return {k.split(".")[0] for k in CONFIG_SCHEMA}


def _check_unknown_sections(data: dict[str, Any], known: set[str]) -> list[str]:
    """Return errors for top-level keys not in *known*."""
    return [f"unknown section '{k}'" for k in data if k not in known]


def _check_value_types(data: dict[str, Any]) -> list[str]:
    """Return errors for schema keys whose values have the wrong type."""
    errors: list[str] = []
    for dotted, meta in CONFIG_SCHEMA.items():
        val = get_nested(data, dotted)
        if val is not _MISSING and not validate_value(val, meta.value_type):
            errors.append(f"'{dotted}': expected {meta.value_type}, got {type(val).__name__}")
    return errors


def _check_unknown_subkeys(data: dict[str, Any], known_sections: set[str]) -> list[str]:
    """Return errors for sub-keys not expected by the schema."""
    errors: list[str] = []
    for section in known_sections:
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            continue
        expected = {k.split(".", 1)[1] for k in CONFIG_SCHEMA if k.startswith(section + ".")}
        for subkey in section_data:
            if subkey not in expected:
                errors.append(f"unknown key '{section}.{subkey}'")
    return errors


def validate_config(data: dict[str, Any]) -> list[str]:
    """Validate a full config dict against the schema.

    Parameters
    ----------
    data : dict
        Parsed config dict (e.g. from the user config file).

    Returns
    -------
    list[str]
        Human-readable error messages.  Empty list means valid.
    """
    if isinstance(data.get("compose"), dict) and "allow_non_repo" in data["compose"]:
        data = {**data, "compose": {**data["compose"]}}
        _migrate_compose_legacy_keys(data)
    known = _known_sections()
    errors = _check_unknown_sections(data, known)
    errors.extend(_check_value_types(data))
    errors.extend(_check_unknown_subkeys(data, known))
    return errors


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def user_config_path() -> Path:
    """Return the path to the user config file."""
    return Path.home() / ".shellenv.toml"


def global_config_path() -> Path:
    """Return the global/site config path.

    Default file is ``/etc/shellenv.toml`` (see ``GLOBAL_CONFIG_PATH``).

    Environment override (for installs and tests):
    - ``SHELLENV_GLOBAL_CONFIG_PATH`` — use another file instead of ``/etc``.
    """
    return Path(str(os.environ.get("SHELLENV_GLOBAL_CONFIG_PATH") or GLOBAL_CONFIG_PATH))


def _strip_none(data: dict) -> dict:
    """Remove keys whose value is ``None`` (TOML has no null literal).

    Recursively cleans nested dicts and drops empty sub-dicts.
    """
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            cleaned = _strip_none(v)
            if cleaned:
                out[k] = cleaned
        elif v is not None:
            out[k] = v
    return out


def load_config(path: Path) -> dict[str, Any]:
    """Load a TOML config file and return its contents as a dict.

    Parameters
    ----------
    path : Path
        File to read.  Missing or malformed files return ``{}``.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if isinstance(data, dict):
            _migrate_compose_legacy_keys(data)
        return data
    except Exception:
        return {}


def save_config(path: Path, data: dict[str, Any]) -> None:
    """Save a config dict to a file as TOML.

    Keys with ``None`` values are omitted (TOML has no null literal).

    Parameters
    ----------
    path : Path
        Destination file.
    data : dict
        Config data to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(_strip_none(data)), encoding="utf8")


# ---------------------------------------------------------------------------
# Merged config loader (schema-driven)
# ---------------------------------------------------------------------------


def _load_cfg_safe(path: Path) -> dict[str, Any]:
    """Load a config file, returning ``{}`` on any error."""
    try:
        if path.exists():
            return load_config(path)
    except Exception:
        pass
    return {}


def _apply_schema_defaults(result: dict[str, Any]) -> None:
    """Populate *result* with default values from the schema."""
    for dotted, meta in CONFIG_SCHEMA.items():
        default = list(meta.default) if isinstance(meta.default, list) else meta.default
        set_nested(result, dotted, default)


def _layer_config(
    result: dict[str, Any],
    source: dict[str, Any],
    global_cfg: dict[str, Any] | None = None,
) -> None:
    """Overlay *source* values onto *result* respecting merge strategies.

    Parameters
    ----------
    result : dict
        Target (modified in place).
    source : dict
        Config to overlay.
    global_cfg : dict or None
        When provided and a key uses ``append`` strategy, the global list
        is used as the base so the final value is global + source.
    """
    for dotted, meta in CONFIG_SCHEMA.items():
        val = get_nested(source, dotted)
        if val is _MISSING:
            continue
        if meta.merge_strategy == "append" and isinstance(val, list) and global_cfg is not None:
            gval = get_nested(global_cfg, dotted)
            base = gval if gval is not _MISSING and isinstance(gval, list) else []
            set_nested(result, dotted, base + val)
        else:
            set_nested(result, dotted, val)


def load_merged_config() -> dict[str, Any]:
    """Load global and user configs and return merged view.

    Schema defaults are applied first, then global values, then user
    values.  List keys with ``merge_strategy="append"`` concatenate
    global and user lists rather than replacing.
    """
    global_cfg = _load_cfg_safe(global_config_path())
    user_cfg = _load_cfg_safe(user_config_path())

    result: dict[str, Any] = {}
    _apply_schema_defaults(result)
    _layer_config(result, global_cfg)
    _layer_config(result, user_cfg, global_cfg=global_cfg)
    return result


def default_config_dict() -> dict[str, Any]:
    """Return nested config dict containing schema defaults."""
    out: dict[str, Any] = {}
    _apply_schema_defaults(out)
    return out


def render_default_config_template() -> str:
    """Render a complete site-wide config template containing all keys.

    ``None`` defaults are emitted as commented ``# key = null`` lines because
    TOML has no native null literal.
    """
    sections: dict[str, list[tuple[str, ConfigKey]]] = {}
    for dotted, meta in CONFIG_SCHEMA.items():
        section, key = dotted.split(".", 1)
        sections.setdefault(section, []).append((key, meta))

    lines: list[str] = [
        "# shellenv global defaults template",
        "# Copy to /etc/shellenv.toml (or SHELLENV_GLOBAL_CONFIG_PATH) and edit.",
        "",
    ]
    for section in sorted(sections):
        lines.append(f"[{section}]")
        for key, meta in sorted(sections[section], key=lambda x: x[0]):
            lines.append(f"# {meta.description}")
            v = meta.default
            if v is None:
                lines.append(f"# {key} = null")
            elif isinstance(v, str):
                lines.append(f'{key} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f"{key} = {'true' if v else 'false'}")
            elif isinstance(v, list):
                quoted = ", ".join(f'"{s}"' for s in v)
                lines.append(f"{key} = [{quoted}]")
            else:
                lines.append(f"{key} = {v}")
            lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_default_config_template(path: Path, *, overwrite: bool = False) -> None:
    """Write the full default config template to *path*."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists (pass overwrite=True to replace)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_default_config_template(), encoding="utf8")


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def config_get(dotted_key: str) -> Any:
    """Return the merged value for *dotted_key*.

    Parameters
    ----------
    dotted_key : str
        A key from ``CONFIG_SCHEMA`` (e.g. ``"trace.threshold_secs"``).

    Returns
    -------
    Any
        The merged value, falling back to the schema default.

    Raises
    ------
    KeyError
        If *dotted_key* is not in the schema.
    """
    if dotted_key not in CONFIG_SCHEMA:
        raise KeyError(f"unknown config key '{dotted_key}'")
    merged = load_merged_config()
    val = get_nested(merged, dotted_key)
    if val is _MISSING:
        return CONFIG_SCHEMA[dotted_key].default
    return val


def config_set(dotted_key: str, value: Any) -> None:
    """Set *value* for *dotted_key* in the user config file.

    Parameters
    ----------
    dotted_key : str
        A key from ``CONFIG_SCHEMA``.
    value : Any
        The new value (must pass type validation).

    Raises
    ------
    KeyError
        If *dotted_key* is not in the schema.
    ValueError
        If *value* does not match the expected type.
    """
    if dotted_key not in CONFIG_SCHEMA:
        raise KeyError(f"unknown config key '{dotted_key}'")
    meta = CONFIG_SCHEMA[dotted_key]
    if not validate_value(value, meta.value_type):
        raise ValueError(f"'{dotted_key}' expects {meta.value_type}, got {type(value).__name__}")
    path = user_config_path()
    data = load_config(path)
    set_nested(data, dotted_key, value)
    save_config(path, data)


def config_reset(dotted_key: str) -> None:
    """Remove *dotted_key* from the user config (reverts to global/default).

    Parameters
    ----------
    dotted_key : str
        A key from ``CONFIG_SCHEMA``.

    Raises
    ------
    KeyError
        If *dotted_key* is not in the schema.
    """
    if dotted_key not in CONFIG_SCHEMA:
        raise KeyError(f"unknown config key '{dotted_key}'")
    path = user_config_path()
    data = load_config(path)
    if delete_nested(data, dotted_key):
        save_config(path, data)


def config_show() -> dict[str, Any]:
    """Return a flat mapping of every schema key to its merged value.

    Returns
    -------
    dict[str, Any]
        Keys are dotted paths, values are the effective setting.
    """
    merged = load_merged_config()
    out: dict[str, Any] = {}
    for dotted, meta in CONFIG_SCHEMA.items():
        val = get_nested(merged, dotted)
        out[dotted] = val if val is not _MISSING else meta.default
    return out
