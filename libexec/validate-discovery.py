#!/usr/bin/env python3
"""Validate shell startup file discovery using shell tracing.

Runs discover_startup_files_modes for each shell family (bash, zsh, tcsh)
with HOME=shelltree/{family}. Discovery uses shell tracing by default.

Reports which files were detected per mode (measured only: no inferred
defaults). There are no CLI flags; run from the repo root.

Usage (recommended — uses project venv and current sources):

  cd /path/to/shellenv
  uv run python libexec/validate-discovery.py

Plain python3 (must see in-tree ``src/shellenv``):

  cd /path/to/shellenv
  PYTHONPATH=src python3 libexec/validate-discovery.py
  or
  PYTHONPATH=src python3 -m shellenv.libexec.validate-discovery

If you only run ``python3`` without ``uv`` and without ``PYTHONPATH=src``,
Python may import an older globally installed ``shellenv`` and zsh
results will not match current tracing.

Requires shelltree/ (run libexec/refresh-shelltree.py first if needed).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure we run from project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if Path.cwd() != PROJECT_ROOT:
    os.chdir(PROJECT_ROOT)
# Package lives under src/ (setuptools src layout)
_src = PROJECT_ROOT / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))

from shellenv.discover import discover_startup_files_modes  # noqa: E402
from shellenv.modes import INVOCATION_MODES  # noqa: E402


def main() -> int:
    """Run validation and print results."""
    shelltree = PROJECT_ROOT / "shelltree"
    if not shelltree.is_dir():
        print("error: shelltree/ not found. Run libexec/refresh-shelltree.py first.")
        return 1

    families = ("bash", "zsh", "tcsh")
    old_home = os.environ.get("HOME")

    for family in families:
        home_dir = shelltree / family
        if not home_dir.is_dir():
            print(f"skip {family}: {home_dir} not found")
            continue

        os.environ["HOME"] = str(home_dir)
        try:
            results = discover_startup_files_modes(
                family,
                shell_path=None,
                use_cache=False,
                include_inferred=False,
            )
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home
            else:
                os.environ.pop("HOME", None)

        print(f"\n--- {family} (HOME={home_dir}) ---")
        for mode in INVOCATION_MODES:
            files = results.get(mode, [])
            print(f"  {mode}: {sorted(files)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
