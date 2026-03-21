"""Compose shell init file selection and installation.

This module scans directories from compose.paths for files matching
{shellrc}-{name}, extracts one-line summaries, and supports selection
and installation into the user's home directory. A registry tracks
selections and their sources for future updates.

Public API
----------
list_compose_files(family, shell_rc_files, paths, allow_non_repo)
    Scan paths and return available compose files with metadata.
install_compose_files(selections, home_dir)
    Copy selected files to home directory and update registry.
get_registry()
    Load the compose selections registry.

Environment (testing)
---------------------
``SHELLCTL_COMPOSE_ALLOW_DIRTY``
    If truthy, accept git repos on ``main``/``master`` even when the working
    tree is dirty. Strict cleanliness is still enforced when unset.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default RC file variants per shell family when config is empty
DEFAULT_SHELL_RC_FILES: dict[str, list[str]] = {
    "zsh": ["zshrc", "zshenv", "zprofile", "zlogin", "zlogout"],
    "bash": ["bashrc", "bash_profile", "bash_login", "profile", "bash_logout"],
    "tcsh": ["tcshrc", "cshrc", "login"],
}


def _registry_path() -> Path:
    """Return the path to the compose registry file."""
    cache = Path(os.environ.get("SHELLCTL_CACHE_DIR") or Path.home() / ".cache" / "shellctl")
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "compose_registry.json"


@dataclass
class ComposeFile:
    """Metadata for a single compose file.

    Attributes
    ----------
    source_path : str
        Absolute path to the source file.
    rc_base : str
        RC variant (e.g. zshrc, zshenv).
    name : str
        Suffix after the hyphen (e.g. fzf, nvm).
    dest_basename : str
        Target basename in home dir (e.g. .zshrc-fzf).
    summary : str
        One-line description extracted from the file.
    """

    source_path: str
    rc_base: str
    name: str
    dest_basename: str
    summary: str


def _extract_summary(path: Path) -> str:
    """Extract a one-line summary from a shell init file.

    Looks for the first significant line: a comment (# or ##) or the
    first non-empty line. Strips leading # and whitespace.

    Parameters
    ----------
    path : Path
        Path to the file.

    Returns
    -------
    str
        Extracted summary, or empty string if none found.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove leading # and ##
        if line.startswith("##"):
            return line[2:].strip()
        if line.startswith("#"):
            return line[1:].strip()
        # First non-comment line as fallback
        return line[:80] + ("..." if len(line) > 80 else "")
    return ""


def _compose_allow_dirty_from_env() -> bool:
    """Check if ``SHELLCTL_COMPOSE_ALLOW_DIRTY`` is set (testing / local use).

    When set, compose still requires a git worktree on ``main``/``master`` but
    allows a non-clean working tree (porcelain output).
    """
    v = os.environ.get("SHELLCTL_COMPOSE_ALLOW_DIRTY", "")
    return str(v).lower() in ("1", "true", "yes", "on")


def _is_repo_on_main(path: Path) -> bool:
    """Check if *path* is in a git repo on main branch at HEAD.

    Parameters
    ----------
    path : Path
        Directory to check (or file; its parent dir is used).

    Returns
    -------
    bool
        True if the directory is a git repo and is on main at HEAD.
    """
    dir_path = path if path.is_dir() else path.parent
    allow_dirty = _compose_allow_dirty_from_env()
    try:
        result = subprocess.run(
            ["git", "-C", str(dir_path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        if "true" not in result.stdout.strip().lower():
            return False

        # Check branch is main and we're at HEAD (no uncommitted, no ahead/behind)
        branch = subprocess.run(
            ["git", "-C", str(dir_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode != 0:
            return False
        current = branch.stdout.strip()
        if current not in ("main", "master"):
            return False

        if allow_dirty:
            return True

        # Check for uncommitted changes or unpushed commits
        status = subprocess.run(
            ["git", "-C", str(dir_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status.returncode != 0:
            return False
        if status.stdout.strip():
            return False  # uncommitted changes

        return True
    except Exception:
        return False


def _shell_rc_files_for_family(
    family: str,
    config_shell_rc: list[str],
) -> list[str]:
    """Return the list of shell RC variants to use.

    Uses config value if non-empty, otherwise family-specific defaults.

    Parameters
    ----------
    family : str
        Shell family (zsh, bash, tcsh).
    config_shell_rc : list[str]
        Value from compose.shell_rc_files config.

    Returns
    -------
    list[str]
        RC base names (e.g. zshrc, zshenv).
    """
    if config_shell_rc:
        return config_shell_rc
    return DEFAULT_SHELL_RC_FILES.get(family.lower(), ["zshrc", "zshenv", "zprofile"])


def list_compose_files(
    family: str,
    shell_rc_files: list[str] | None = None,
    paths: list[str] | None = None,
    allow_non_repo: bool | None = None,
) -> list[ComposeFile]:
    """Scan compose paths for available shell init files.

    Files must match the pattern {shellrc}-{name} (e.g. zshrc-fzf).
    By default, directories not in a git repo or not on main:HEAD are
    skipped unless allow_non_repo is True.

    Parameters
    ----------
    family : str
        Shell family (zsh, bash, tcsh).
    shell_rc_files : list[str] or None
        RC variants to look for. If None, uses config or family defaults.
    paths : list[str] or None
        Directories to scan. If None, uses compose.paths from config.
    allow_non_repo : bool
        If True, include directories that are not git repos or not on main.

    Returns
    -------
    list[ComposeFile]
        Available compose files with metadata.
    """
    from .config import load_merged_config

    cfg = load_merged_config()
    if paths is None:
        paths = cfg.get("compose", {}).get("paths") or []
    if shell_rc_files is None:
        config_rc = cfg.get("compose", {}).get("shell_rc_files") or []
        shell_rc_files = _shell_rc_files_for_family(family, config_rc)

    logger.debug(
        "list_compose_files: family=%r paths=%r shell_rc_files=%r",
        family,
        paths,
        shell_rc_files,
    )

    if not paths:
        logger.debug("list_compose_files: no paths configured, returning empty")
        return []

    # Use config for allow_non_repo when not explicitly passed
    if allow_non_repo is None:
        allow_cfg = cfg.get("compose", {}).get("allow_non_repo", "false")
        allow_non_repo = (
            str(allow_cfg).lower() in ("true", "1", "yes") if allow_cfg is not None else False
        )

    logger.debug("list_compose_files: allow_non_repo=%r", allow_non_repo)

    result: list[ComposeFile] = []
    seen: set[tuple[str, str]] = set()  # (rc_base, name) to dedupe

    for dir_str in paths:
        dir_path = Path(dir_str).expanduser().resolve()
        if not dir_path.is_dir():
            logger.debug("list_compose_files: skipping %r (not a directory)", dir_path)
            continue

        if not allow_non_repo and not _is_repo_on_main(dir_path):
            logger.debug(
                "list_compose_files: skipping %r (not a git repo on main:HEAD)",
                dir_path,
            )
            continue

        logger.debug("list_compose_files: scanning directory %r", dir_path)

        for rc_base in shell_rc_files:
            pattern = re.compile(rf"^{re.escape(rc_base)}-(.+)$")
            for entry in dir_path.iterdir():
                if not entry.is_file():
                    continue
                m = pattern.match(entry.name)
                if not m:
                    continue
                name = m.group(1)
                key = (rc_base, name)
                if key in seen:
                    logger.debug(
                        "list_compose_files: skipping %s (duplicate)",
                        entry.name,
                    )
                    continue
                seen.add(key)

                dest_basename = f".{rc_base}-{name}"
                summary = _extract_summary(entry)
                logger.debug(
                    "list_compose_files: found %s -> %s (summary=%r)",
                    entry.name,
                    dest_basename,
                    summary[:50] if summary else "",
                )
                result.append(
                    ComposeFile(
                        source_path=str(entry),
                        rc_base=rc_base,
                        name=name,
                        dest_basename=dest_basename,
                        summary=summary or "(no description)",
                    )
                )

    logger.debug(
        "list_compose_files: found %d compose file(s) from %d path(s)",
        len(result),
        len(paths),
    )
    return sorted(result, key=lambda c: (c.rc_base, c.name))


def get_registry() -> list[dict[str, Any]]:
    """Load the compose selections registry.

    Returns
    -------
    list[dict]
        List of selection records. Each has keys: source_path, dest_basename,
        rc_base, name, installed_at (optional).
    """
    path = _registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("selections", [])
    except Exception:
        return []


def _save_registry(selections: list[dict[str, Any]]) -> None:
    """Write the registry to disk."""
    path = _registry_path()
    path.write_text(
        json.dumps({"selections": selections}, indent=2),
        encoding="utf-8",
    )


def install_compose_files(
    selections: list[ComposeFile],
    home_dir: Path | None = None,
) -> list[str]:
    """Copy selected compose files to the home directory.

    Each file is installed as ~/.{rc_base}-{name}. The registry is
    updated with the source path for each installed file.

    Parameters
    ----------
    selections : list[ComposeFile]
        Compose files to install.
    home_dir : Path or None
        Target directory. Defaults to Path.home().

    Returns
    -------
    list[str]
        Absolute paths of installed files.
    """
    home = home_dir or Path.home()
    registry = get_registry()
    installed: list[str] = []
    reg_by_dest: dict[str, dict] = {r["dest_basename"]: r for r in registry}

    for cf in selections:
        dest = home / cf.dest_basename
        try:
            shutil.copy2(cf.source_path, dest)
            installed.append(str(dest))
            reg_by_dest[cf.dest_basename] = {
                "source_path": cf.source_path,
                "dest_basename": cf.dest_basename,
                "rc_base": cf.rc_base,
                "name": cf.name,
            }
        except Exception:
            raise

    # Persist registry
    _save_registry(list(reg_by_dest.values()))

    return installed
