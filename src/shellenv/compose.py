"""Compose shell init file selection and installation.

This module scans directories from compose.paths for files matching
{shellrc}-{name}, extracts one-line summaries, and supports selection
and installation into the user's home directory. A registry tracks
selections and their sources for future updates.

Public API
----------
list_compose_files(family, shell_rc_files, paths, allow_non_repo)
    Scan paths and return available compose files with metadata.
split_compose_by_summary_valid(files)
    Split results into valid vs invalid summary headers.
install_compose_files(selections, home_dir)
    Symlink selected files into home and update registry.
get_registry()
    Load the compose selections registry.
compose_parent_rc_warnings(selections, home_dir, family)
    After install, return human-readable warnings if parent rc files do not
    appear to source ``~/.{rc_base}-*`` fragments (PROJECT.md).

Environment (testing)
---------------------
``SHELLENV_COMPOSE_ALLOW_DIRTY``
    If truthy, accept git repos on ``main``/``master`` even when the working
    tree is dirty. Strict cleanliness is still enforced when unset.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Shown when the first non-blank, non-shebang line is not a ``#`` comment summary
INVALID_COMPOSE_SUMMARY = (
    "[invalid] first non-blank line must be a # comment (not #!); see PROJECT.md compose"
)

# Default RC file variants per shell family when config is empty
DEFAULT_SHELL_RC_FILES: dict[str, list[str]] = {
    "zsh": ["zshrc", "zshenv", "zprofile", "zlogin", "zlogout"],
    "bash": ["bashrc", "bash_profile", "bash_login", "profile", "bash_logout"],
    "tcsh": ["tcshrc", "cshrc", "login"],
}


def _registry_path() -> Path:
    """Return the path to the compose registry file."""
    cache = Path(os.environ.get("SHELLENV_CACHE_DIR") or Path.home() / ".cache" / "shellenv")
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
        One-line description extracted from the file, or
        :data:`INVALID_COMPOSE_SUMMARY` when the header rule is not met.
    summary_valid : bool
        False when the first substantive line is not a ``#`` summary comment
        (after optional ``#!`` shebang lines).
    """

    source_path: str
    rc_base: str
    name: str
    dest_basename: str
    summary: str
    summary_valid: bool = True


def _parse_compose_summary(path: Path) -> tuple[str, bool]:
    """Parse the required leading comment summary from a compose fragment.

    The first non-blank line must be a shell ``#`` comment (not ``#!``).
    Any ``#!`` lines at the top are skipped so sourced fragments may keep a
    shebang.

    Returns
    -------
    tuple[str, bool]
        ``(summary_text, True)`` when valid, or ``("", False)`` when invalid.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ("", False)

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#!"):
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if not body:
                return ("(empty # comment)", True)
            return (body, True)
        return ("", False)
    return ("", False)


def _extract_summary(path: Path) -> str:
    """Return the summary text only; empty string if invalid or unreadable."""
    summary, valid = _parse_compose_summary(path)
    return summary if valid else ""


def _compose_allow_dirty_from_env() -> bool:
    """Check if ``SHELLENV_COMPOSE_ALLOW_DIRTY`` is set (testing / local use).

    When set, compose still requires a git worktree on ``main``/``master`` but
    allows a non-clean working tree (porcelain output).
    """
    v = os.environ.get("SHELLENV_COMPOSE_ALLOW_DIRTY", "")
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


def _looks_like_git_url(value: str) -> bool:
    """Return True when *value* looks like a git clone URL."""
    return "://" in value or value.startswith("git@")


def _compose_sources_root(cfg: dict[str, Any]) -> Path:
    """Return local clone root for compose source URLs."""
    tool_root = cfg.get("shellenv", {}).get("tool_repo_path") or "~/.shellenv"
    return Path(str(tool_root)).expanduser() / "compose-sources"


def _source_repo_dir_for_id(source_id: str, root: Path) -> Path:
    """Map a source identifier to a deterministic local clone directory."""
    token = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:12]  # noqa: S324
    tail = source_id.rstrip("/").split("/")[-1].replace(".git", "") or "repo"
    safe_tail = re.sub(r"[^A-Za-z0-9._-]+", "-", tail).strip("-") or "repo"
    return root / f"{safe_tail}-{token}"


def _resolve_repo_source(source: str) -> tuple[str, str] | None:
    """Resolve a source as (source_id, clone_from)."""
    if _looks_like_git_url(source):
        return (source, source)

    path = Path(source).expanduser()
    if not path.exists():
        return None
    resolved = path.resolve()
    return (resolved.as_uri(), str(resolved))


def _ensure_cloned_source(source_id: str, clone_from: str, root: Path) -> Path | None:
    """Clone or fast-forward update source into *root*, return local directory."""
    root.mkdir(parents=True, exist_ok=True)
    dest = _source_repo_dir_for_id(source_id, root)
    try:
        if (dest / ".git").exists():
            subprocess.run(
                ["git", "-C", str(dest), "pull", "--ff-only"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            subprocess.run(
                ["git", "clone", "--depth", "1", clone_from, str(dest)],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        return dest
    except Exception as exc:
        logger.warning("compose: failed to clone/update %s: %s", clone_from, exc)
        return None


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
        Available compose files with metadata. Entries with invalid summaries
        (no leading ``#`` comment per :func:`_parse_compose_summary`) are sorted
        after all valid entries.
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

    clone_root = _compose_sources_root(cfg)

    for source in paths:
        source_str = str(source).strip()
        if not source_str:
            continue

        repo_source = _resolve_repo_source(source_str)
        if repo_source is None:
            logger.debug("list_compose_files: skipping %r (source not found)", source_str)
            continue
        source_id, clone_from = repo_source
        local = _ensure_cloned_source(source_id, clone_from, clone_root)
        if local is None:
            continue
        dir_path = local.resolve()

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
                summary, summary_valid = _parse_compose_summary(entry)
                if not summary_valid:
                    summary = INVALID_COMPOSE_SUMMARY
                logger.debug(
                    "list_compose_files: found %s -> %s (summary=%r valid=%s)",
                    entry.name,
                    dest_basename,
                    summary[:50] if summary else "",
                    summary_valid,
                )
                result.append(
                    ComposeFile(
                        source_path=str(entry),
                        rc_base=rc_base,
                        name=name,
                        dest_basename=dest_basename,
                        summary=summary,
                        summary_valid=summary_valid,
                    )
                )

    logger.debug(
        "list_compose_files: found %d compose file(s) from %d path(s)",
        len(result),
        len(paths),
    )
    return sorted(
        result,
        key=lambda c: (0 if c.summary_valid else 1, c.rc_base, c.name),
    )


def _parent_rc_sources_fragments(content: str, rc_base: str) -> bool:
    """Return True if *content* plausibly loads ``~/.{rc_base}-*`` fragments."""
    if not content or not content.strip():
        return False
    eb = re.escape(rc_base)
    dot = rf"\.{eb}-"
    # Explicit glob on fragment basename
    if re.search(rf"{dot}\\*", content):
        return True
    if re.search(rf"(?:\$HOME|\$\{{HOME\}}|~)/\.{eb}-\*", content):
        return True
    # Parentheses glob (tcsh): ($HOME/.tcshrc-*)
    if re.search(rf"\([^)]*{dot}\*", content):
        return True
    # for / foreach iterating over fragment paths
    if re.search(rf"for\s+[^\n#]*{dot}", content, re.IGNORECASE):
        return True
    if re.search(rf"foreach\s+[^\n#]*{dot}", content, re.IGNORECASE):
        return True
    return False


def _example_parent_rc_loop(rc_base: str, family: str) -> str:
    """Return a short example stanza for sourcing compose fragments."""
    fam = family.lower()
    if fam == "tcsh":
        return (
            f"  foreach _rc ($HOME/.{rc_base}-*)\n"
            f'      if (-f "$_rc") source "$_rc"\n'
            f"  end"
        )
    return (
        f"  for _rc in $HOME/.{rc_base}-*; do\n"
        f'      [ -f "$_rc" ] && . "$_rc"\n'
        f"  done"
    )


def compose_parent_rc_warnings(
    selections: list[ComposeFile],
    home_dir: Path | None = None,
    *,
    family: str = "zsh",
) -> list[str]:
    """Check parent rc files for compose fragment sourcing loops (PROJECT.md).

    Emits at most one message per distinct ``rc_base`` among *selections*.
    """
    if not selections:
        return []

    home = home_dir or Path.home()
    fam = family.lower()
    warned_rc: set[str] = set()
    out: list[str] = []

    for cf in selections:
        rc = cf.rc_base
        if rc in warned_rc:
            continue
        warned_rc.add(rc)

        parent = home / f".{rc}"
        example = _example_parent_rc_loop(rc, fam)
        shell_hint = "bash/zsh" if fam != "tcsh" else "tcsh"

        if not parent.exists():
            out.append(
                f"warning: parent startup file {parent} does not exist. "
                f"Compose installed fragments like ~/{cf.dest_basename}; "
                f"create {parent} and add a loop so the shell loads ~/.{rc}-* files.\n"
                f"Example ({shell_hint}):\n{example}"
            )
            continue

        try:
            text = parent.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            out.append(
                f"warning: could not read {parent}: {exc}. "
                f"Verify it sources ~/.{rc}-* compose fragments.\n"
                f"Example ({shell_hint}):\n{example}"
            )
            continue

        if _parent_rc_sources_fragments(text, rc):
            continue

        out.append(
            f"warning: {parent} does not appear to source ~/.{rc}-* compose fragments. "
            f"Files like ~/{cf.dest_basename} may never load unless you add a loop.\n"
            f"Example ({shell_hint}):\n{example}"
        )

    return out


def split_compose_by_summary_valid(
    files: list[ComposeFile],
) -> tuple[list[ComposeFile], list[ComposeFile]]:
    """Split *files* into valid-summary and invalid-summary lists.

    Order within each list follows *files* order.
    """
    valid: list[ComposeFile] = []
    invalid: list[ComposeFile] = []
    for f in files:
        (valid if f.summary_valid else invalid).append(f)
    return valid, invalid


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
    """Symlink selected compose files into the home directory.

    Each file is installed as ~/.{rc_base}-{name} symlinked to its source. The registry is
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
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            dest.symlink_to(Path(cf.source_path))
            installed.append(str(dest))
            reg_by_dest[cf.dest_basename] = {
                "source_path": cf.source_path,
                "dest_basename": cf.dest_basename,
                "rc_base": cf.rc_base,
                "name": cf.name,
                "install_mode": "symlink",
            }
        except Exception:
            raise

    # Persist registry
    _save_registry(list(reg_by_dest.values()))

    return installed
