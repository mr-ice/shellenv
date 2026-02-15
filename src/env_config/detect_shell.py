"""Shell detection utilities.

Provides robust detection of the current/login shell and the intended
shell using a precedence order and normalization to known shell
families.
"""
from __future__ import annotations

import os
import pwd
import shutil
import subprocess

KNOWN_SHELLS = {"bash", "zsh", "tcsh", "csh", "sh", "dash", "ksh", "fish"}


def _parent_process_info() -> tuple[str | None, str | None]:
    """Return (comm, args) for parent process or (None, None) on failure."""
    try:
        ppid = os.getppid()
        # Ask ps for the executable name and full args. Works on macOS and Linux.
        out_comm = subprocess.check_output(["ps", "-p", str(ppid), "-o", "comm="], text=True)
        out_args = subprocess.check_output(["ps", "-p", str(ppid), "-o", "args="], text=True)
        return out_comm.strip(), out_args.strip()
    except Exception:
        return None, None


def _normalize_to_path(candidate: str) -> str | None:
    """Try to turn a candidate (path or basename) into an executable path.

    Returns full path if resolvable, otherwise returns candidate if it
    looks like an absolute path (even if not present on disk), otherwise
    resolves with `which` or returns None.
    """
    if not candidate:
        return None
    # If candidate is an absolute path and exists, keep it
    if os.path.isabs(candidate):
        return candidate
    # If candidate appears like '/bin/zsh --login', extract first token
    first = candidate.split()[0]
    if os.path.isabs(first) and os.path.exists(first):
        return first
    # Try to resolve by name on PATH
    which = shutil.which(first)
    if which:
        return which
    return None


def _family_from_path(path: str | None) -> str | None:
    if not path:
        return None
    base = os.path.basename(path)
    # strip common prefixes like -zsh (login shells), and any args
    base = base.lstrip("-")
    base = base.split()[0]
    name = base.split("-")[0]
    if name in KNOWN_SHELLS:
        return name
    return None


def detect_current_and_intended_shell(cli_arg: str | None = None) -> dict[str, str | None]:
    """Detect login shell, SHELL env, parent process, and intended shell.

    Precedence used to choose the intended shell:
    1. `cli_arg` if provided
    2. `SHELL` environment variable
    3. parent process if it looks like a shell
    4. login shell from passwd entry

    Returned dict keys:
    - login_shell: login shell from passwd (path or None)
    - shell_env: value of $SHELL (or None)
    - parent_comm: parent process executable name (or None)
    - parent_args: parent process args (or None)
    - intended_shell: resolved path to intended shell (or None)
    - intended_family: normalized family name (bash/zsh/tcsh/etc.) or None
    - resolved_source: which source won (cli|env|parent|login|none)
    """
    try:
        login_shell = pwd.getpwuid(os.getuid()).pw_shell
    except Exception:
        login_shell = None

    shell_env = os.environ.get("SHELL")
    parent_comm, parent_args = _parent_process_info()

    resolved = None
    source = "none"

    if cli_arg:
        resolved = _normalize_to_path(cli_arg)
        source = "cli"
    elif shell_env:
        resolved = _normalize_to_path(shell_env)
        source = "env"
    else:
        # consider parent only if it looks like a shell name
        if parent_comm:
            fam = _family_from_path(parent_comm)
            if fam:
                resolved = _normalize_to_path(parent_comm)
                source = "parent"

    if not resolved and login_shell:
        resolved = _normalize_to_path(login_shell)
        source = source if source != "none" else "login"

    family = _family_from_path(resolved) if resolved else None

    return {
        "login_shell": login_shell,
        "shell_env": shell_env,
        "parent_comm": parent_comm,
        "parent_args": parent_args,
        "intended_shell": resolved,
        "intended_family": family,
        "resolved_source": source,
    }
