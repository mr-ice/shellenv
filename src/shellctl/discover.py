"""Startup-file discovery for shells.

This module provides a safe discovery strategy:
- Try to use system tracers (`strace` on Linux, `dtruss` on macOS) to see
  which files are opened when the shell starts.
- If tracers are unavailable or fail, fall back to a curated list of
  candidate startup files for common shells (bash, zsh, tcsh).
- Cache simple results under the user's cache directory.

The tracer approach is best-effort; use with care. For now discovery
exposes a simple API suitable for unit testing and CLI display.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

CACHE_DIR = Path(os.environ.get("SHELLENV_CACHE_DIR") or Path.home() / ".cache" / "shellenv")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(family: str, mode: str | None = None) -> Path:
    suffix = f"_{mode}" if mode else ""
    return CACHE_DIR / f"discovered_{family}{suffix}.json"


def clear_cache(family: str | None = None, mode: str | None = None) -> None:
    """Clear cached discovery results.

    If `family` is None, clear all discovery caches. If `mode` is
    provided, clear only that family's mode cache.
    """
    if family is None:
        # remove any discovered_*.json files
        for p in CACHE_DIR.glob("discovered_*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        return

    p = _cache_path(family, mode)
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass


def _save_cache(family: str, files: Iterable[str], mode: str | None = None) -> None:
    p = _cache_path(family, mode)
    p.write_text(json.dumps(sorted(set(files))), encoding="utf8")


def _load_cache(family: str, mode: str | None = None) -> list[str]:
    p = _cache_path(family, mode)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf8"))
    except Exception:
        return []


# Valid startup file prefixes per family (basename must match or start with one of these).
# Used to filter out wrong-shell files when tracer misreports (e.g. running zsh instead of tcsh).
_FAMILY_FILE_PREFIXES: dict[str, tuple[str, ...]] = {
    "bash": (".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_logout", ".bash_env"),
    "zsh": (".zshenv", ".zshrc", ".zprofile", ".zlogin", ".zlogout"),
    "tcsh": (".tcshrc", ".cshrc", ".login", ".tcshenv"),
}


def _is_valid_for_family(path_or_name: str, family: str) -> bool:
    """Return True if basename is a valid startup file for the given family."""
    family = family.lower()
    # zsh startup files commonly source helpers from ~/.zshlib/*
    if family == "zsh":
        rel = path_or_name.lstrip("/")
        if rel.startswith(".zshlib/"):
            return True
    prefixes = _FAMILY_FILE_PREFIXES.get(family, ())
    base = os.path.basename(path_or_name.lstrip("/"))
    return any(base == p or base.startswith(p + "-") for p in prefixes)


def _run_tracer(family: str, shell_path: str, args: list[str]) -> set[str]:
    """Run shell trace collection and return startup files under $HOME.

    Returns a set of home-relative file paths discovered.
    If tracing fails, returns an empty set.
    """
    home = str(Path.home())
    files: set[str] = set()

    try:
        # import here to avoid top-level dependency cycles
        from .trace import collect_startup_file_traces

        traces = collect_startup_file_traces(
            family,
            shell_path=shell_path,
            args=args,
            dry_run=False,
        )
        if isinstance(traces, str):
            return set()
        home = str(Path.home())
        for ft in traces:
            # Only include files under $HOME (user's startup files)
            abs_path = os.path.normpath(os.path.abspath(os.path.expanduser(ft.path)))
            if home and not abs_path.startswith(home):
                continue
            rel = os.path.relpath(abs_path, home)
            if rel:
                files.add(rel)
        return files
    except Exception:
        return set()


def discover_startup_files_modes(
    family: str,
    shell_path: str | None = None,
    use_cache: bool = True,
    *,
    include_inferred: bool = True,
    existing_only: bool = False,
    full_paths: bool = False,
    modes: list[str] | None = None,
) -> dict:
    """Discover startup files for each invocation mode (login/interactive combos).

    Parameters
    ----------
    modes : list[str] or None
        Modes to discover. If None, use all INVOCATION_MODES.

    Returns
    -------
    dict
        Mapping mode -> list of file basenames.
    """
    from .modes import INVOCATION_MODES, mode_to_args

    family = family.lower()
    mode_list = modes if modes is not None else list(INVOCATION_MODES)
    results: dict[str, list[str]] = {}

    # Resolve shell path for tracing; required to actually trace sourced files.
    # For tcsh, prefer patched tcsh with TCSH_XTRACEFD (see patches/README.md).
    # Do not use shell_path from detection when it points to a different shell
    # (e.g. /bin/zsh); that would trace the wrong shell and return wrong files.
    if family == "bash":
        from .trace import get_bash_for_tracing

        if shell_path and os.path.basename(shell_path).lower() == "bash":
            tracer_shell = get_bash_for_tracing(shell_path)
        else:
            tracer_shell = get_bash_for_tracing(None)
        tracer_shell = tracer_shell or shutil.which("bash")
    elif family == "tcsh" or family == "csh":
        from .trace import get_tcsh_for_tracing

        if shell_path and os.path.basename(shell_path).lower() in ("tcsh", "csh"):
            tracer_shell = get_tcsh_for_tracing(shell_path)
        else:
            tracer_shell = get_tcsh_for_tracing(None)
        tracer_shell = tracer_shell or shutil.which("tcsh")
    else:
        tracer_shell = shell_path or shutil.which(family) or shutil.which(f"/bin/{family}")

    for mode in mode_list:
        if mode not in INVOCATION_MODES:
            continue
        traced: set[str] = set()
        args = mode_to_args(family, mode)
        if tracer_shell:
            traced = _run_tracer(family, tracer_shell, args)

        if not traced and use_cache:
            traced = set(_load_cache(family, mode))

        result: list[str] = []
        seen: set[str] = set()

        # Prioritize traced: when we have traced files, use them as authoritative.
        # Filter to family-appropriate files only (avoids wrong-shell traces e.g.
        # zsh when tcsh fails).
        for f in sorted(traced):
            if f and f not in seen and _is_valid_for_family(f, family):
                result.append(f)
                seen.add(f)

        if include_inferred:
            # Include canonical entry points as a fallback when callers want
            # inferred candidates in addition to traced ones.
            extra = [f".{family}rc", f".{family}env"]
            for e in extra:
                if e not in seen:
                    result.append(e)
                    seen.add(e)

        # optionally filter to existing files and/or return full paths
        processed: list[str] = []
        for name in result:
            if full_paths:
                cand = os.path.join(str(Path.home()), name)
            else:
                cand = name
            if existing_only:
                check_path = cand if os.path.isabs(cand) else os.path.join(str(Path.home()), name)
                if not os.path.exists(check_path):
                    continue
            processed.append(cand)

        try:
            _save_cache(family, result, mode)
        except Exception:
            pass

        results[mode] = processed

    return results


def discover_startup_files(
    family: str,
    shell_path: str | None = None,
    use_cache: bool = True,
    *,
    include_inferred: bool = True,
    existing_only: bool = False,
    full_paths: bool = False,
    modes: list[str] | None = None,
) -> list[str]:
    """Backward-compatible wrapper: returns union of all mode lists (deduped)."""
    from .modes import INVOCATION_MODES

    mode_results = discover_startup_files_modes(
        family,
        shell_path=shell_path,
        use_cache=use_cache,
        include_inferred=include_inferred,
        existing_only=existing_only,
        full_paths=full_paths,
        modes=modes,
    )
    seen: set[str] = set()
    out: list[str] = []
    for mode in INVOCATION_MODES:
        for f in mode_results.get(mode, []):
            if f not in seen:
                out.append(f)
                seen.add(f)
    return out
