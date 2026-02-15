"""Simple curses-based TUI for presenting trace analysis results."""

from __future__ import annotations

import curses
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def resolve_path(name: str) -> str:
    """Resolve a possibly-relative startup file name to an absolute path.

    If `name` is absolute, return it unchanged. Otherwise treat it as relative
    to the user's home directory.
    """
    if os.path.isabs(name):
        return name
    return os.path.normpath(os.path.join(os.path.expanduser("~"), name))


def backup_file(path: str) -> bool:
    """Create a timestamped backup of `path` into the backup directory.

    Backup directory is taken from `ENVCONFIG_BACKUP_DIR` or defaults to
    `~/.cache/env-config/backups`.
    """
    try:
        p = Path(path)
        if not p.exists():
            return False
        backup_dir = Path(
            os.environ.get("ENVCONFIG_BACKUP_DIR")
            or Path.home() / ".cache" / "env-config" / "backups"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        dest = backup_dir / f"{ts}_{p.name}"
        shutil.copy2(str(p), str(dest))
        return True
    except Exception:
        return False


def disable_file(path: str) -> bool:
    """Disable a file by backing it up and renaming it with a .disabled suffix.

    Returns True if the rename succeeded (backup may succeed or fail).
    """
    try:
        # attempt to back up but don't need the return value here
        backup_file(path)
        dest = f"{path}.disabled"
        os.rename(path, dest)
        return True
    except Exception:
        return False


def _draw_screen(stdscr, analysis: dict[str, Any], top: int, selected: int):
    """Draw the main screen with the list of files and their timings."""
    stdscr.clear()
    stdscr.border()
    stdscr.addstr(1, 2, "env-config: startup trace analysis")
    total = analysis.get("total", 0.0)
    stdscr.addstr(2, 2, f"Total: {total:.6f}s")
    stdscr.addstr(3, 2, "Flags: '!' = exceeded threshold; navigate with Up/Down; Enter for details")
    header_y = 5
    stdscr.addstr(
        header_y - 1, 2, "Idx File                              Duration   Cmds   %   Reasons"
    )

    items = analysis.get("items", [])
    h, w = stdscr.getmaxyx()
    display_lines = h - (header_y + 3)
    for idx in range(display_lines):
        i = top + idx
        y = header_y + idx
        if i >= len(items):
            break
        item = items[i]
        flag = "!" if item.get("flagged") else " "
        file = item.get("file")
        dur = item.get("duration")
        cmds = item.get("commands")
        pct = item.get("percent")
        reasons = ",".join(item.get("reasons", []))
        line = f"{i:3d} {flag} {file[:30]:30} {dur:9.6f} {cmds:5d} {pct:5.1f}% {reasons}"
        try:
            if i == selected:
                stdscr.addstr(y, 2, line, curses.A_REVERSE)
            else:
                stdscr.addstr(y, 2, line)
        except curses.error:
            pass

    stdscr.addstr(h - 2, 2, "q=quit  r=refresh  Enter=details")
    stdscr.refresh()


def display_trace_tui(analysis: dict[str, Any]) -> None:
    """Display the trace analysis results in a simple TUI."""

    def _wrapper(stdscr):
        curses.curs_set(0)
        top = 0
        selected = 0
        items = analysis.get("items", [])
        h, w = stdscr.getmaxyx()
        display_lines = h - 8
        _draw_screen(stdscr, analysis, top, selected)
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (curses.KEY_DOWN, ord("j")):
                if selected < len(items) - 1:
                    selected += 1
                    if selected >= top + display_lines:
                        top += 1
            elif ch in (curses.KEY_UP, ord("k")):
                if selected > 0:
                    selected -= 1
                    if selected < top:
                        top = max(0, top - 1)
            elif ch in (ord("r"), ord("R")):
                # refresh screen
                pass
            elif ch in (curses.KEY_ENTER, 10, 13):
                # show details popup
                if 0 <= selected < len(items):
                    it = items[selected]
                    stdscr.clear()
                    stdscr.border()
                    stdscr.addstr(1, 2, f"Details for: {it.get('file')}")
                    stdscr.addstr(3, 2, f"Duration: {it.get('duration'):.6f}s")
                    stdscr.addstr(4, 2, f"Commands: {it.get('commands')}")
                    stdscr.addstr(5, 2, f"Percent: {it.get('percent'):.2f}%")
                    stdscr.addstr(7, 2, f"Reasons: {', '.join(it.get('reasons', []))}")
                    stdscr.addstr(h - 2, 2, "Press any key to return")
                    stdscr.getch()
            _draw_screen(stdscr, analysis, top, selected)

    curses.wrapper(_wrapper)


def launch_tui() -> None:
    """Launch the TUI with placeholder data."""
    raise NotImplementedError("Use display_trace_tui(analysis) to show trace results")


def display_discovery_tui(modes: dict[str, list[str]]) -> None:
    """Display discovery per-mode results in a simple TUI.

    Controls:
    - Left/Right: switch mode
    - Up/Down (j/k): move selection
    - Enter: show file details
    - q: quit
    """
    mode_keys = list(modes.keys())

    def _wrapper(stdscr):
        curses.curs_set(0)
        selected_idx = 0
        mode_idx = 0
        top = 0

        def draw():
            stdscr.clear()
            stdscr.border()
            h, w = stdscr.getmaxyx()
            stdscr.addstr(1, 2, "env-config: discovery (per-mode)")
            stdscr.addstr(2, 2, "Left/Right: switch mode  Up/Down: move  Enter: details  q: quit")
            stdscr.addstr(4, 2, f"Mode: {mode_keys[mode_idx]}")
            items = modes.get(mode_keys[mode_idx], [])
            header_y = 6
            stdscr.addstr(header_y - 1, 2, "Idx File")
            display_lines = h - (header_y + 4)
            for i in range(display_lines):
                idx = top + i
                y = header_y + i
                if idx >= len(items):
                    break
                name = items[idx]
                line = f"{idx:3d} {name[:w-10]:{w-10}}"
                try:
                    if idx == selected_idx:
                        stdscr.addstr(y, 2, line, curses.A_REVERSE)
                    else:
                        stdscr.addstr(y, 2, line)
                except curses.error:
                    pass
            stdscr.addstr(h - 2, 2, "q=quit")
            stdscr.refresh()

        def _confirm(prompt: str) -> bool:
            stdscr.clear()
            stdscr.border()
            stdscr.addstr(2, 2, prompt)
            stdscr.addstr(4, 2, "y=yes  n=no")
            stdscr.refresh()
            while True:
                ch = stdscr.getch()
                if ch in (ord("y"), ord("Y")):
                    return True
                if ch in (ord("n"), ord("N")):
                    return False

        def _status(msg: str) -> None:
            h, w = stdscr.getmaxyx()
            try:
                stdscr.addstr(h - 3, 2, " " * (w - 4))
                stdscr.addstr(h - 3, 2, msg[: w - 4])
                stdscr.refresh()
            except curses.error:
                pass

        def _open_in_editor(path: str) -> bool:
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
            try:
                curses.endwin()
                subprocess.run([editor, path])
                stdscr.refresh()
                return True
            except Exception:
                return False

        draw()
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (curses.KEY_RIGHT, ord("l")):
                if mode_idx < len(mode_keys) - 1:
                    mode_idx += 1
                    selected_idx = 0
                    top = 0
            elif ch in (curses.KEY_LEFT, ord("h")):
                if mode_idx > 0:
                    mode_idx -= 1
                    selected_idx = 0
                    top = 0
            elif ch in (curses.KEY_DOWN, ord("j")):
                items = modes.get(mode_keys[mode_idx], [])
                if selected_idx < max(0, len(items) - 1):
                    selected_idx += 1
                    h, w = stdscr.getmaxyx()
                    display_lines = h - 10
                    if selected_idx >= top + display_lines:
                        top += 1
            elif ch in (curses.KEY_UP, ord("k")):
                if selected_idx > 0:
                    selected_idx -= 1
                    if selected_idx < top:
                        top = max(0, top - 1)
            elif ch in (curses.KEY_ENTER, 10, 13):
                items = modes.get(mode_keys[mode_idx], [])
                if 0 <= selected_idx < len(items):
                    it = items[selected_idx]
                    stdscr.clear()
                    stdscr.border()
                    stdscr.addstr(1, 2, f"Details for: {it}")
                    stdscr.addstr(3, 2, f"Path: {it}")
                    stdscr.addstr(5, 2, "Press any key to return")
                    stdscr.getch()
            elif ch in (ord("b"), ord("B")):
                items = modes.get(mode_keys[mode_idx], [])
                if 0 <= selected_idx < len(items):
                    it = items[selected_idx]
                    path = resolve_path(it)
                    ok = backup_file(path)
                    _status("Backup succeeded" if ok else "Backup failed")
            elif ch in (ord("o"), ord("O")):
                items = modes.get(mode_keys[mode_idx], [])
                if 0 <= selected_idx < len(items):
                    it = items[selected_idx]
                    path = resolve_path(it)
                    if not os.path.exists(path):
                        _status("File does not exist")
                    else:
                        _status("Opening editor...")
                        _open_in_editor(path)
                        _status("Returned from editor")
            elif ch in (ord("d"), ord("D")):
                items = modes.get(mode_keys[mode_idx], [])
                if 0 <= selected_idx < len(items):
                    it = items[selected_idx]
                    path = resolve_path(it)
                    if not os.path.exists(path):
                        _status("File does not exist")
                    else:
                        if _confirm(f"Disable {path}? This will rename the file."):
                            backed = backup_file(path)
                            try:
                                dest = f"{path}.disabled"
                                os.rename(path, dest)
                                _status(
                                    "Disabled (renamed) and backed up"
                                    if backed
                                    else "Disabled (renamed)"
                                )
                            except Exception:
                                _status("Disable failed")
            draw()

    curses.wrapper(_wrapper)
