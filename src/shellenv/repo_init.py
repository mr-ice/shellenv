"""Clone/update the configured startup-files repo and install files into ``~``.

Implements PROJECT.md features 9–10: ``repo.url`` / ``repo.destination`` / ``repo.branch``,
``init-repo`` (clone, verify remote, branch / fast-forward), and ``init`` (backup-then-copy
from ``<destination>/<family>/`` into the home directory).
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

from .discover import _is_valid_for_family

# Resolve the git binary once at import time so calls succeed even when the
# process environment has a stripped PATH (e.g. `env - uv run shellenv init`).
# Fall back to common install locations when PATH is empty.
_GIT_FALLBACK_PATHS = ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git")
_GIT: str = shutil.which("git") or next(
    (p for p in _GIT_FALLBACK_PATHS if Path(p).exists()),
    "git",  # last-resort: let subprocess raise a clear FileNotFoundError
)


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _expand_path(s: str) -> Path:
    return Path(os.path.expanduser(s)).expanduser().resolve()


def _normalize_remote_url(url: str) -> str:
    """Loose equality for ``git remote`` URLs (paths resolved; https lowercased)."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    if u.startswith("file:"):
        parsed = urllib.parse.urlparse(u)
        path = urllib.parse.unquote(parsed.path or "")
        try:
            return str(Path(path).resolve()).lower()
        except Exception:
            return str(Path(path)).lower()
    if u.startswith("/"):
        try:
            return str(Path(u).resolve()).lower()
        except Exception:
            return u.lower()
    return u.lower()


def remote_urls_match(configured: str, origin: str) -> bool:
    """Return True if *configured* and *origin* refer to the same logical repository."""
    return _normalize_remote_url(configured) == _normalize_remote_url(origin)


def is_git_worktree(path: Path) -> bool:
    """Determine is git worktree."""
    p = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return p.returncode == 0 and p.stdout.strip() == "true"


def get_origin_url(repo: Path) -> str | None:
    """Determine origin URL of git worktree."""
    p = _run_git(["remote", "get-url", "origin"], cwd=repo)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def current_branch(repo: Path) -> str | None:
    """Determine current branch of git worktree."""
    p = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def is_worktree_dirty(repo: Path) -> bool:
    """Determine is git worktree dirty."""
    p = _run_git(["status", "--porcelain"], cwd=repo)
    return p.returncode == 0 and bool(p.stdout.strip())


def commits_behind_upstream(repo: Path, branch: str) -> int:
    """Count commits on ``origin/<branch>`` not in ``HEAD`` (0 if no upstream / ambiguous)."""
    p = _run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], cwd=repo)
    if p.returncode != 0:
        return 0
    try:
        return max(0, int(p.stdout.strip()))
    except ValueError:
        return 0


def load_repo_settings_from_config(cfg: dict[str, Any]) -> tuple[str, Path, str]:
    """Return ``(url, destination, branch)`` from a merged config dict."""
    repo = cfg.get("repo") or {}
    if not isinstance(repo, dict):
        repo = {}
    url = repo.get("url")
    dest = repo.get("destination")
    branch = repo.get("branch") or "main"
    if not isinstance(url, str) or not url.strip():
        raise ValueError("repo.url is not set in configuration")
    if not isinstance(dest, str) or not dest.strip():
        raise ValueError("repo.destination is not set in configuration")
    if not isinstance(branch, str) or not branch.strip():
        branch = "main"
    return url.strip(), _expand_path(dest), branch.strip()


def ensure_startup_repo_ready(
    *,
    fix: bool = False,
    cfg: dict[str, Any] | None = None,
) -> list[str]:
    """Clone or update the repo at ``repo.destination``; verify it matches ``repo.url``.

    Parameters
    ----------
    fix
        If True, switch to ``repo.branch`` when on a different branch and run
        ``git pull --ff-only`` when behind ``origin/<branch>``.
    cfg
        Merged config dict. If None, :func:`shellenv.config.load_merged_config` is used.

    Returns
    -------
    list[str]
        Warning lines (printed by the caller). Non-fixable problems raise ``RuntimeError``.

    Raises
    ------
    ValueError
        Missing ``repo.url`` / ``repo.destination``.
    RuntimeError
        Path is not a clone of the configured URL, git errors, etc.
    """
    from .config import load_merged_config

    if cfg is None:
        cfg = load_merged_config()
    url, dest, branch = load_repo_settings_from_config(cfg)
    warnings: list[str] = []

    if dest.exists() and not is_git_worktree(dest):
        if dest.is_dir() and not any(dest.iterdir()):
            pass  # empty directory — clone into it below
        else:
            raise RuntimeError(
                f"repo.destination exists but is not a git worktree: {dest}\n"
                "Remove it or point repo.destination elsewhere."
            )

    if not dest.exists() or (dest.exists() and not is_git_worktree(dest)):
        dest.parent.mkdir(parents=True, exist_ok=True)
        clone_cmd = ["clone", "--origin", "origin", "-b", branch, url, str(dest)]
        p = _run_git(clone_cmd)
        if p.returncode == 0:
            return warnings
        # Retry without -b (remote may use master only, or branch name mismatch)
        p2 = _run_git(["clone", "--origin", "origin", url, str(dest)])
        if p2.returncode != 0:
            raise RuntimeError(
                f"git clone failed:\n{p2.stderr or p2.stdout or p.stderr or p.stdout}"
            )
        b = current_branch(dest)
        if b and b != branch:
            warnings.append(f"cloned default branch is {b!r}, configured repo.branch is {branch!r}")
            if fix:
                co = _run_git(["checkout", branch], cwd=dest)
                if co.returncode != 0:
                    co_m = _run_git(["checkout", "-b", branch, f"origin/{branch}"], cwd=dest)
                    if co_m.returncode != 0:
                        raise RuntimeError(
                            f"could not switch to branch {branch!r}:\n{co.stderr or co_m.stderr}"
                        )
        return warnings

    if not is_git_worktree(dest):
        raise RuntimeError(f"not a git repository: {dest}")

    origin = get_origin_url(dest)
    if origin is None:
        raise RuntimeError(f"no origin remote in {dest}; expected clone of {url!r}")
    if not remote_urls_match(url, origin):
        raise RuntimeError(
            f"repo.destination is not a clone of repo.url.\n"
            f"  configured url: {url!r}\n"
            f"  origin remote:  {origin!r}"
        )

    fetch = _run_git(["fetch", "origin"], cwd=dest)
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch failed in {dest}:\n{fetch.stderr or fetch.stdout}")

    cur = current_branch(dest)
    if cur and cur != branch:
        warnings.append(
            f"on branch {cur!r}, configured repo.branch is {branch!r} "
            "(use shellenv init-repo --fix to switch and fast-forward)"
        )
        if fix:
            co = _run_git(["checkout", branch], cwd=dest)
            if co.returncode != 0:
                cob = _run_git(["checkout", "-b", branch, f"origin/{branch}"], cwd=dest)
                if cob.returncode != 0:
                    raise RuntimeError(f"could not checkout {branch!r}:\n{co.stderr or cob.stderr}")

    behind = commits_behind_upstream(dest, branch)
    if behind > 0:
        warnings.append(
            f"behind origin/{branch} by {behind} commit(s) "
            "(use shellenv init-repo --fix to git pull --ff-only)"
        )
        if fix:
            pull = _run_git(["pull", "--ff-only", "origin", branch], cwd=dest)
            if pull.returncode != 0:
                raise RuntimeError(f"git pull --ff-only failed:\n{pull.stderr or pull.stdout}")

    if is_worktree_dirty(dest):
        warnings.append(f"working tree has local changes in {dest}")

    return warnings


def iter_family_init_files(repo_root: Path, family: str) -> list[tuple[Path, str]]:
    """List ``(source_path, home_relative_path)`` under ``repo_root/<family>/``.

    Only regular files whose basenames are valid startup names for *family* are included.
    """
    family = family.lower()
    base = repo_root / family
    if not base.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(base.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not _is_valid_for_family(name, family):
            continue
        out.append((path, name))
    return out


def is_home_file_covered_by_newer_backup(
    rel_path: str,
    *,
    home: Path | None = None,
    backup_dir: Path | None = None,
) -> bool:
    """Is shellenv backup archive newer than the home file lists *rel_path*."""
    from .backup import list_archives, read_manifest

    if home is None:
        home = Path.home()
    target = home / rel_path
    if not target.exists():
        return True
    file_mtime = target.stat().st_mtime
    for _, arpath in list_archives(backup_dir):
        try:
            man = read_manifest(arpath)
        except Exception:
            continue
        if rel_path not in man.files:
            continue
        try:
            if arpath.stat().st_mtime >= file_mtime:
                return True
        except OSError:
            continue
    return False


def plan_init_install(
    repo_root: Path,
    family: str,
    *,
    home: Path | None = None,
    backup_dir: Path | None = None,
) -> tuple[list[tuple[Path, str]], list[str]]:
    """Compute copy plan and home-relative paths that need backup before overwrite.

    Returns
    -------
    (copies, backup_rel_paths)
        *copies* is ``(src, home_rel)`` pairs to copy (skip when already identical).
        *backup_rel_paths* are paths that exist, differ from source, and are not covered.
    """
    if home is None:
        home = Path.home()
    copies: list[tuple[Path, str]] = []
    backup_needed: list[str] = []
    for src, rel in iter_family_init_files(repo_root, family):
        dest = home / rel
        if dest.exists() and filecmp.cmp(src, dest, shallow=False):
            continue
        copies.append((src, rel))
        if dest.exists() and not filecmp.cmp(src, dest, shallow=False):
            if not is_home_file_covered_by_newer_backup(rel, home=home, backup_dir=backup_dir):
                backup_needed.append(rel)
    return copies, backup_needed


def run_init_home(
    family: str,
    *,
    fix_repo: bool = False,
    yes: bool = False,
    cfg: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Ensure repo is ready, back up files that would be overwritten, copy from repo.

    Returns
    -------
    (warnings, copied_relpaths)
    """
    from .backup import create_backup
    from .config import load_merged_config

    if cfg is None:
        cfg = load_merged_config()

    warnings = ensure_startup_repo_ready(fix=fix_repo, cfg=cfg)
    _url, dest, _branch = load_repo_settings_from_config(cfg)
    home = Path.home()

    copies, backup_rel = plan_init_install(dest, family, home=home)
    if not copies:
        return warnings, []

    abs_backup = [str(home / r) for r in backup_rel if (home / r).exists()]
    if abs_backup:
        if not yes:
            print("The following existing file(s) would be overwritten and are not covered by a")
            print("newer shellenv backup archive; they will be backed up first:")
            for p in abs_backup:
                print(f"  {p}")
            answer = input("Proceed? [y/N] ").strip().lower()
            if answer != "y":
                raise RuntimeError("cancelled")
        create_backup(abs_backup, family)

    copied: list[str] = []
    for src, rel in copies:
        dest_path = home / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        copied.append(rel)
    return warnings, copied
