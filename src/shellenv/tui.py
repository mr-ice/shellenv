"""Simple curses-based TUI for presenting trace analysis and config editing.

Public Functions
----------------
display_trace_tui(analysis)
    Show trace analysis in a scrollable curses view.
display_discovery_tui(modes)
    Show per-mode discovery results.
display_config_tui()
    Interactive config key/value editor.
validate_editor_config(path)
    Validate a TOML config file on disk; returns a list of error strings.
display_backup_tui(files, family, archive_mode)
    Interactive file selection for backup/archive operations.
display_restore_tui(backup_dir)
    Interactive archive browser and file restore.
"""

from __future__ import annotations

import curses
import os
import shutil
import sys
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
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

    Backup directory is taken from `SHELLENV_BACKUP_DIR` and defaults to
    `~/.cache/shellenv/backups`.
    """
    try:
        p = Path(path)
        if not p.exists():
            return False
        backup_dir = Path(
            os.environ.get("SHELLENV_BACKUP_DIR") or Path.home() / ".cache" / "shellenv" / "backups"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
    stdscr.addstr(1, 2, "shellenv: startup trace analysis")
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

        def _open_in_editor(path: str) -> bool:
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
            try:
                curses.endwin()
                subprocess.run([editor, path])
                stdscr.refresh()
                return True
            except Exception:
                return False

        def _view_file_contents(path: str) -> None:
            try:
                with open(path, encoding="utf8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except Exception as exc:
                lines = [f"Failed to read {path}: {exc}"]

            top_line = 0
            while True:
                stdscr.clear()
                stdscr.border()
                h2, w2 = stdscr.getmaxyx()
                stdscr.addstr(1, 2, f"Viewing: {path}"[: w2 - 4])
                stdscr.addstr(2, 2, "Up/Down scroll  PgUp/PgDn page  q back")
                body_h = h2 - 6
                for i in range(max(0, body_h)):
                    idx = top_line + i
                    if idx >= len(lines):
                        break
                    try:
                        stdscr.addstr(4 + i, 2, lines[idx][: w2 - 4])
                    except curses.error:
                        pass
                try:
                    max_lines = max(1, len(lines))
                    first_line = min(max_lines, top_line + 1)
                    last_visible_idx = min(len(lines), top_line + max(0, body_h))
                    last_is_end = len(lines) > 0 and last_visible_idx >= len(lines)
                    last_label = "END" if last_is_end else str(max(first_line, last_visible_idx))
                    stdscr.addstr(h2 - 2, 2, f"Lines {first_line}-{last_label}/{max_lines}")
                except curses.error:
                    pass
                stdscr.refresh()

                ch2 = stdscr.getch()
                if ch2 in (ord("q"), ord("Q"), 27):
                    return
                if ch2 in (curses.KEY_DOWN, ord("j")):
                    if top_line < max(0, len(lines) - 1):
                        top_line += 1
                elif ch2 in (curses.KEY_UP, ord("k")):
                    top_line = max(0, top_line - 1)
                elif ch2 in (curses.KEY_NPAGE,):
                    top_line = min(max(0, len(lines) - 1), top_line + max(1, body_h))
                elif ch2 in (curses.KEY_PPAGE,):
                    top_line = max(0, top_line - max(1, body_h))

        def _show_details(item: dict[str, Any]) -> None:
            path = resolve_path(str(item.get("file", "")))
            while True:
                stdscr.clear()
                stdscr.border()
                h2, w2 = stdscr.getmaxyx()
                stdscr.addstr(1, 2, f"Details for: {item.get('file')}"[: w2 - 4])
                stdscr.addstr(3, 2, f"Path: {path}"[: w2 - 4])
                stdscr.addstr(4, 2, f"Exists: {'yes' if os.path.exists(path) else 'no'}")
                stdscr.addstr(6, 2, f"Trace commands: {item.get('commands', 0)}")
                stdscr.addstr(
                    7,
                    2,
                    f"Trace duration: {float(item.get('duration', 0.0)):.6f}s",
                )
                stdscr.addstr(8, 2, f"Percent: {float(item.get('percent', 0.0)):.2f}%")
                stdscr.addstr(
                    9,
                    2,
                    f"Reasons: {', '.join(item.get('reasons', [])) or '-'}"[: w2 - 4],
                )
                stdscr.addstr(h2 - 3, 2, "v=view file  o=open editor  any other key=back")
                stdscr.refresh()

                ch2 = stdscr.getch()
                if ch2 in (ord("v"), ord("V")):
                    _view_file_contents(path)
                    continue
                if ch2 in (ord("o"), ord("O")):
                    if os.path.exists(path):
                        _open_in_editor(path)
                    continue
                return

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
                if 0 <= selected < len(items):
                    _show_details(items[selected])
            _draw_screen(stdscr, analysis, top, selected)

    curses.wrapper(_wrapper)


def launch_tui() -> None:
    """Launch the TUI with placeholder data."""
    raise NotImplementedError("Use display_trace_tui(analysis) to show trace results")


def display_discovery_tui(
    modes: dict[str, list[str]],
    details: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> None:
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
            stdscr.addstr(1, 2, "shellenv: discovery (per-mode)")
            stdscr.addstr(
                2,
                2,
                "Left/Right: switch mode  Up/Down: move  Enter: details  q: quit",
            )
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
                line = f"{idx:3d} {name[: w - 10]:{w - 10}}"
                try:
                    if idx == selected_idx:
                        stdscr.addstr(y, 2, line, curses.A_REVERSE)
                    else:
                        stdscr.addstr(y, 2, line)
                except curses.error:
                    pass
            stdscr.addstr(h - 2, 2, "q=quit  o=open editor  b=backup  d=disable")
            stdscr.refresh()

        def _view_file_contents(path: str) -> None:
            try:
                with open(path, encoding="utf8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except Exception as exc:
                lines = [f"Failed to read {path}: {exc}"]

            top_line = 0
            while True:
                stdscr.clear()
                stdscr.border()
                h, w = stdscr.getmaxyx()
                stdscr.addstr(1, 2, f"Viewing: {path}"[: w - 4])
                stdscr.addstr(2, 2, "Up/Down scroll  PgUp/PgDn page  q back")
                body_h = h - 6
                for i in range(max(0, body_h)):
                    idx = top_line + i
                    if idx >= len(lines):
                        break
                    try:
                        stdscr.addstr(4 + i, 2, lines[idx][: w - 4])
                    except curses.error:
                        pass
                try:
                    max_lines = max(1, len(lines))
                    first_line = min(max_lines, top_line + 1)
                    last_visible_idx = min(len(lines), top_line + max(0, body_h))
                    last_is_end = len(lines) > 0 and last_visible_idx >= len(lines)
                    last_label = "END" if last_is_end else str(max(first_line, last_visible_idx))
                    stdscr.addstr(
                        h - 2,
                        2,
                        f"Lines {first_line}-{last_label}/{max_lines}",
                    )
                except curses.error:
                    pass
                stdscr.refresh()

                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q"), 27):
                    return
                if ch in (curses.KEY_DOWN, ord("j")):
                    if top_line < max(0, len(lines) - 1):
                        top_line += 1
                elif ch in (curses.KEY_UP, ord("k")):
                    top_line = max(0, top_line - 1)
                elif ch in (curses.KEY_NPAGE,):
                    top_line = min(max(0, len(lines) - 1), top_line + max(1, body_h))
                elif ch in (curses.KEY_PPAGE,):
                    top_line = max(0, top_line - max(1, body_h))

        def _show_details(name: str, mode: str) -> None:
            path = resolve_path(name)
            per_mode = details.get(mode, {}) if details else {}
            info = per_mode.get(name) or per_mode.get(path) or {}
            present_in_modes = [mk for mk, items in modes.items() if name in items or path in items]
            while True:
                stdscr.clear()
                stdscr.border()
                h, w = stdscr.getmaxyx()
                stdscr.addstr(1, 2, f"Details for: {name}"[: w - 4])
                stdscr.addstr(3, 2, f"Mode: {mode}"[: w - 4])
                stdscr.addstr(4, 2, f"Path: {path}"[: w - 4])
                stdscr.addstr(5, 2, f"Exists: {'yes' if os.path.exists(path) else 'no'}")
                stdscr.addstr(
                    6,
                    2,
                    f"Loaded in modes: {', '.join(present_in_modes) or '-'}"[: w - 4],
                )
                if os.path.exists(path):
                    try:
                        stdscr.addstr(7, 2, f"Size: {os.path.getsize(path)} bytes")
                    except OSError:
                        pass
                if info:
                    stdscr.addstr(9, 2, f"Trace commands: {info.get('commands', 0)}")
                    stdscr.addstr(
                        10,
                        2,
                        f"Trace duration: {float(info.get('duration', 0.0)):.6f}s",
                    )
                stdscr.addstr(h - 3, 2, "v=view file  o=open editor  any other key=back")
                stdscr.refresh()

                ch = stdscr.getch()
                if ch in (ord("v"), ord("V")):
                    _view_file_contents(path)
                    continue
                if ch in (ord("o"), ord("O")):
                    if os.path.exists(path):
                        _open_in_editor(path)
                    else:
                        _status("File does not exist")
                    continue
                return

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
                    _show_details(it, mode_keys[mode_idx])
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


# ---------------------------------------------------------------------------
# Checklist (checkbox multi-select) — reusable component
# ---------------------------------------------------------------------------


@dataclass
class ChecklistState:
    """State for a checkbox multi-select list.

    Attributes
    ----------
    items : list[str]
        Display labels for each item.
    checked : list[bool]
        Whether each item is selected.
    selected : int
        Cursor position.
    top : int
        First visible item index (for scrolling).
    """

    items: list[str]
    checked: list[bool]
    selected: int = 0
    top: int = 0


def _checklist_nav(ch: int, state: ChecklistState, display_lines: int) -> ChecklistState:
    """Process a keypress for checklist navigation.

    Handles Up/Down/j/k movement, Space to toggle the selected item,
    ``a`` to select all, and ``n`` to deselect all.

    Parameters
    ----------
    ch : int
        Character code from ``stdscr.getch()``.
    state : ChecklistState
        Current checklist state (mutated in place).
    display_lines : int
        Number of visible rows for scrolling calculations.

    Returns
    -------
    ChecklistState
        The same *state* object, returned for convenience.
    """
    n = len(state.items)
    if ch in (curses.KEY_DOWN, ord("j")) and state.selected < n - 1:
        state.selected += 1
        if state.selected >= state.top + display_lines:
            state.top += 1
    elif ch in (curses.KEY_UP, ord("k")) and state.selected > 0:
        state.selected -= 1
        if state.selected < state.top:
            state.top = max(0, state.top - 1)
    elif ch == ord(" ") and 0 <= state.selected < n:
        state.checked[state.selected] = not state.checked[state.selected]
    elif ch in (ord("a"), ord("A")):
        state.checked = [True] * n
    elif ch in (ord("n"), ord("N")):
        state.checked = [False] * n
    return state


def _draw_checklist(
    stdscr,
    state: ChecklistState,
    title: str,
    subtitle: str,
    footer: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Render a checkbox list with ``[x]``/``[ ]`` markers.

    Parameters
    ----------
    stdscr
        Curses window.
    state : ChecklistState
        Current checklist state.
    title : str
        First header line.
    subtitle : str
        Second header line (controls hint).
    footer : str
        Bottom status bar text.
    extra_lines : list[str] or None
        Additional info lines shown between subtitle and the list.
    """
    stdscr.clear()
    stdscr.border()
    h, w = stdscr.getmaxyx()
    try:
        stdscr.addstr(1, 2, title[: w - 4])
        stdscr.addstr(2, 2, subtitle[: w - 4])
    except curses.error:
        pass

    info_y = 4
    if extra_lines:
        for i, line in enumerate(extra_lines):
            try:
                stdscr.addstr(info_y + i, 2, line[: w - 4])
            except curses.error:
                pass
        info_y += len(extra_lines) + 1

    header_y = info_y
    display_lines = h - (header_y + 3)
    for i in range(max(0, display_lines)):
        idx = state.top + i
        y = header_y + i
        if idx >= len(state.items):
            break
        mark = "[x]" if state.checked[idx] else "[ ]"
        label = state.items[idx]
        line = f"{mark} {label}"
        line = line[: w - 4]
        try:
            attr = curses.A_REVERSE if idx == state.selected else 0
            stdscr.addstr(y, 2, line, attr)
        except curses.error:
            pass

    try:
        stdscr.addstr(h - 2, 2, footer[: w - 4])
    except curses.error:
        pass
    stdscr.refresh()


# ---------------------------------------------------------------------------
# Backup / Archive TUI
# ---------------------------------------------------------------------------


def _prepare_backup(files: list[str], checked: list[bool]) -> list[str]:
    """Return the subset of *files* where the corresponding entry is checked.

    Parameters
    ----------
    files : list[str]
        All candidate file paths.
    checked : list[bool]
        Selection state for each file.

    Returns
    -------
    list[str]
        Selected file paths.

    Raises
    ------
    ValueError
        If no files are selected.
    """
    selected = [f for f, c in zip(files, checked) if c]
    if not selected:
        raise ValueError("no files selected")
    return selected


def _build_backup_items(
    file_groups: list[tuple[str, list[str]]],
    active_family: str,
) -> tuple[list[str], list[bool], list[int]]:
    """Build a flat item list from grouped files, active family first.

    Parameters
    ----------
    file_groups : list[tuple[str, list[str]]]
        Each entry is ``(family, [absolute_paths])``.  Order within each
        group is preserved.
    active_family : str
        The detected/active shell family.  Its files appear first and are
        pre-checked; other families' files start unchecked.

    Returns
    -------
    tuple[list[str], list[bool], list[int]]
        ``(display_labels, default_checked, group_start_indices)``

        *display_labels*
            Labels shown in the checklist.  Group headers are encoded as
            separator strings (e.g. ``"── bash (active) ──"``).
        *default_checked*
            Initial checked state — ``True`` for active family files,
            ``False`` for others.
        *group_start_indices*
            Indices into *display_labels* that are group-header separators
            (non-selectable).
    """
    labels: list[str] = []
    checked: list[bool] = []
    separators: list[int] = []

    # Active family first
    active_files: list[str] = []
    other_groups: list[tuple[str, list[str]]] = []
    for fam, flist in file_groups:
        if fam == active_family:
            active_files = flist
        else:
            other_groups.append((fam, flist))

    if active_files:
        separators.append(len(labels))
        labels.append(f"── {active_family} (active) ──")
        checked.append(False)  # separator not selectable
        for f in active_files:
            labels.append(f)
            checked.append(True)

    for fam, flist in other_groups:
        if not flist:
            continue
        separators.append(len(labels))
        labels.append(f"── {fam} ──")
        checked.append(False)
        for f in flist:
            labels.append(f)
            checked.append(False)

    return labels, checked, separators


def _draw_backup_checklist(
    stdscr,
    state: ChecklistState,
    separators: list[int],
    title: str,
    subtitle: str,
    footer: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Render a grouped checkbox list with family-header separators.

    Separator rows are rendered bold without a checkbox.  File rows use
    the standard ``[x]``/``[ ]`` markers.

    Parameters
    ----------
    stdscr
        Curses window.
    state : ChecklistState
        Current checklist state.
    separators : list[int]
        Indices in ``state.items`` that are group-header separators.
    title : str
        First header line.
    subtitle : str
        Second header line (controls hint).
    footer : str
        Bottom status bar text.
    extra_lines : list[str] or None
        Additional info lines shown between subtitle and the list.
    """
    sep_set = set(separators)
    stdscr.clear()
    stdscr.border()
    h, w = stdscr.getmaxyx()
    try:
        stdscr.addstr(1, 2, title[: w - 4])
        stdscr.addstr(2, 2, subtitle[: w - 4])
    except curses.error:
        pass

    info_y = 4
    if extra_lines:
        for i, line in enumerate(extra_lines):
            try:
                stdscr.addstr(info_y + i, 2, line[: w - 4])
            except curses.error:
                pass
        info_y += len(extra_lines) + 1

    header_y = info_y
    display_lines = h - (header_y + 3)
    for i in range(max(0, display_lines)):
        idx = state.top + i
        y = header_y + i
        if idx >= len(state.items):
            break
        if idx in sep_set:
            # Group header — bold, no checkbox
            line = state.items[idx][: w - 4]
            try:
                attr = curses.A_BOLD
                if idx == state.selected:
                    attr |= curses.A_REVERSE
                stdscr.addstr(y, 2, line, attr)
            except curses.error:
                pass
        else:
            mark = "[x]" if state.checked[idx] else "[ ]"
            line = f"{mark} {state.items[idx]}"
            line = line[: w - 4]
            try:
                attr = curses.A_REVERSE if idx == state.selected else 0
                stdscr.addstr(y, 2, line, attr)
            except curses.error:
                pass

    try:
        stdscr.addstr(h - 2, 2, footer[: w - 4])
    except curses.error:
        pass
    stdscr.refresh()


def display_backup_tui(
    file_groups: list[tuple[str, list[str]]],
    active_family: str,
    archive_mode: bool = False,
) -> Path | None:
    """Interactive TUI for selecting files to back up.

    Shows files from all shell families, grouped with headers.  The active
    family's files appear first and are pre-checked; other families start
    unchecked.

    Parameters
    ----------
    file_groups : list[tuple[str, list[str]]]
        Each entry is ``(family, [absolute_paths])``.
    active_family : str
        The detected/active shell family (shown first, pre-checked).
    archive_mode : bool
        If True, originals are deleted after backup (archive behavior).

    Returns
    -------
    Path or None
        Path to created archive, or ``None`` if the user cancelled.
    """
    from .backup import create_archive, create_backup

    labels, default_checked, separators = _build_backup_items(file_groups, active_family)
    sep_set = set(separators)

    # Build flat list of actual file paths (excluding separators)
    all_files: list[str] = [labels[i] for i in range(len(labels)) if i not in sep_set]

    result: list[Path | None] = [None]

    def _wrapper(stdscr):
        curses.curs_set(0)
        state = ChecklistState(
            items=list(labels),
            checked=list(default_checked),
        )
        # Skip cursor past first separator if present
        if separators and state.selected in sep_set:
            state.selected = min(state.selected + 1, len(labels) - 1)
        status = ""

        def _draw():
            n_sel = sum(c for i, c in enumerate(state.checked) if i not in sep_set)
            n_total = len(all_files)
            mode_label = "archive (backup + delete)" if archive_mode else "backup"
            extra = [
                f"Active family: {active_family}    Mode: {mode_label}",
                f"Files: {n_sel} selected / {n_total} total",
            ]
            if status:
                extra.append(status)
            _draw_backup_checklist(
                stdscr,
                state,
                separators,
                title="shellenv: select files to back up",
                subtitle="Space: toggle  a: all  n: none  Enter: create  q: quit",
                footer="q=quit  Space=toggle  a=all  n=none  Enter=create backup",
                extra_lines=extra,
            )

        def _confirm(prompt: str) -> bool:
            stdscr.clear()
            stdscr.border()
            try:
                stdscr.addstr(2, 2, prompt)
                stdscr.addstr(4, 2, "y=yes  n=no")
            except curses.error:
                pass
            stdscr.refresh()
            while True:
                ch = stdscr.getch()
                if ch in (ord("y"), ord("Y")):
                    return True
                if ch in (ord("n"), ord("N")):
                    return False

        _draw()
        while True:
            ch = stdscr.getch()
            h, _ = stdscr.getmaxyx()
            display_lines = h - 11

            if ch in (ord("q"), ord("Q")):
                break

            # Navigation — skip separators
            old_sel = state.selected
            _checklist_nav(ch, state, display_lines)
            # If we landed on a separator, skip past it in the direction of travel
            if state.selected in sep_set:
                direction = 1 if state.selected > old_sel else -1
                state.selected += direction
                state.selected = max(0, min(state.selected, len(labels) - 1))
                # If still on a separator (edge case), find next non-sep
                while state.selected in sep_set and 0 < state.selected < len(labels) - 1:
                    state.selected += direction

            if ch in (curses.KEY_ENTER, 10, 13):
                # Gather checked files (excluding separators)
                selected_files = [
                    labels[i] for i in range(len(labels)) if i not in sep_set and state.checked[i]
                ]
                if not selected_files:
                    status = "No files selected"
                    _draw()
                    continue

                if archive_mode:
                    msg = f"Back up and DELETE {len(selected_files)} file(s)?"
                else:
                    msg = f"Back up {len(selected_files)} file(s)?"

                if _confirm(msg):
                    try:
                        if archive_mode:
                            result[0] = create_archive(selected_files, active_family)
                        else:
                            result[0] = create_backup(selected_files, active_family)
                        status = f"Created: {result[0]}"
                    except Exception as exc:
                        status = f"Error: {exc}"
                    _draw()
                    stdscr.getch()
                    break

            _draw()

    curses.wrapper(_wrapper)
    return result[0]


# ---------------------------------------------------------------------------
# Restore TUI
# ---------------------------------------------------------------------------


def _archive_list_for_display(
    archives: list[tuple[str, Path]],
) -> list[dict[str, str]]:
    """Build display data for archive selection.

    Reads manifests and returns dicts with metadata for each archive.
    Handles unreadable manifests gracefully.

    Parameters
    ----------
    archives : list[tuple[str, Path]]
        Output from :func:`backup.list_archives`.

    Returns
    -------
    list[dict[str, str]]
        Each dict has keys: ``timestamp``, ``family``, ``hostname``,
        ``file_count``, ``path``.
    """
    from .backup import read_manifest

    result = []
    for timestamp, path in archives:
        try:
            manifest = read_manifest(path)
            result.append(
                {
                    "timestamp": timestamp,
                    "family": manifest.family,
                    "hostname": manifest.hostname,
                    "file_count": str(len(manifest.files)),
                    "path": str(path),
                }
            )
        except Exception:
            result.append(
                {
                    "timestamp": timestamp,
                    "family": "?",
                    "hostname": "?",
                    "file_count": "?",
                    "path": str(path),
                }
            )
    return result


def _restore_file_status(
    manifest_files: list[str],
    target_dir: Path,
) -> list[tuple[str, bool]]:
    """Check which manifest files already exist on disk.

    Parameters
    ----------
    manifest_files : list[str]
        Relative file paths from the archive manifest.
    target_dir : Path
        Target directory (usually ``Path.home()``).

    Returns
    -------
    list[tuple[str, bool]]
        Each entry is ``(relative_path, already_exists)``.
    """
    return [(f, (target_dir / f).exists()) for f in manifest_files]


def display_restore_tui(backup_dir: Path | None = None) -> list[str]:
    """Interactive TUI for browsing archives and restoring files.

    Two-phase workflow: first select an archive, then select files to
    restore from that archive.

    Parameters
    ----------
    backup_dir : Path or None
        Override backup directory.  Defaults to :func:`backup.get_backup_dir`.

    Returns
    -------
    list[str]
        Absolute paths of restored files (empty if cancelled).
    """
    from .backup import list_archives, read_manifest, restore_from_archive

    restored_files: list[str] = []

    def _wrapper(stdscr):
        curses.curs_set(0)
        archives = list_archives(backup_dir)
        if not archives:
            stdscr.clear()
            stdscr.border()
            try:
                stdscr.addstr(2, 2, "No backup archives found.")
                stdscr.addstr(4, 2, "Press any key to exit.")
            except curses.error:
                pass
            stdscr.refresh()
            stdscr.getch()
            return

        display_data = _archive_list_for_display(archives)

        # --- Phase 1: archive selection ---
        selected = 0
        top = 0

        def _draw_archive_list():
            stdscr.clear()
            stdscr.border()
            h, w = stdscr.getmaxyx()
            try:
                stdscr.addstr(1, 2, "shellenv: restore from backup")
                stdscr.addstr(2, 2, "Up/Down: navigate  Enter: select archive  q: quit")
                stdscr.addstr(4, 2, "Available archives:")
            except curses.error:
                pass
            header_y = 6
            display_lines = h - (header_y + 3)
            for i in range(max(0, display_lines)):
                idx = top + i
                y = header_y + i
                if idx >= len(display_data):
                    break
                d = display_data[idx]
                line = (
                    f"{d['timestamp']}  ({d['file_count']} files)  {d['family']}  {d['hostname']}"
                )
                line = line[: w - 4]
                try:
                    attr = curses.A_REVERSE if idx == selected else 0
                    stdscr.addstr(y, 2, line, attr)
                except curses.error:
                    pass
            try:
                stdscr.addstr(h - 2, 2, "q=quit  Enter=select")
            except curses.error:
                pass
            stdscr.refresh()

        def _confirm(prompt: str) -> bool:
            stdscr.clear()
            stdscr.border()
            try:
                stdscr.addstr(2, 2, prompt)
                stdscr.addstr(4, 2, "y=yes  n=no")
            except curses.error:
                pass
            stdscr.refresh()
            while True:
                ch = stdscr.getch()
                if ch in (ord("y"), ord("Y")):
                    return True
                if ch in (ord("n"), ord("N")):
                    return False

        _draw_archive_list()
        chosen_archive = None
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                return

            h, _ = stdscr.getmaxyx()
            display_lines = h - 9
            selected, top = _config_nav(ch, selected, top, len(archives), display_lines)

            if ch in (curses.KEY_ENTER, 10, 13):
                chosen_archive = archives[selected][1]
                break

            _draw_archive_list()

        # --- Phase 2: file selection from chosen archive ---
        manifest = read_manifest(chosen_archive)
        target_dir = Path.home()
        file_status = _restore_file_status(manifest.files, target_dir)
        labels = [f"{name}  (exists)" if exists else name for name, exists in file_status]
        state = ChecklistState(
            items=labels,
            checked=[True] * len(labels),
        )
        force = False
        status = ""

        def _draw_restore():
            n_sel = sum(state.checked)
            force_label = "YES" if force else "NO"
            extra = [
                f"Archive: {chosen_archive.name}  ({manifest.timestamp})",
                f"Force overwrite: {force_label}    Files: {n_sel} selected / {len(labels)} total",
            ]
            if status:
                extra.append(status)
            _draw_checklist(
                stdscr,
                state,
                title="shellenv: select files to restore",
                subtitle="Space: toggle  a: all  n: none  f: force  Enter: restore  q: back",
                footer="q=back  Space=toggle  f=force  Enter=restore",
                extra_lines=extra,
            )

        _draw_restore()
        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                # go back to archive list — for simplicity, just exit
                break

            h, _ = stdscr.getmaxyx()
            display_lines = h - 12

            _checklist_nav(ch, state, display_lines)

            if ch in (ord("f"), ord("F")):
                force = not force

            if ch in (curses.KEY_ENTER, 10, 13):
                selected_files = [manifest.files[i] for i, c in enumerate(state.checked) if c]
                if not selected_files:
                    status = "No files selected"
                    _draw_restore()
                    continue

                action = "restore (overwrite)" if force else "restore (skip existing)"
                if _confirm(f"{action} {len(selected_files)} file(s)?"):
                    try:
                        result = restore_from_archive(
                            chosen_archive,
                            target_dir=target_dir,
                            include=[os.path.basename(f) for f in selected_files],
                            force=force,
                        )
                        restored_files.extend(result)
                        status = f"Restored {len(result)} file(s)"
                    except Exception as exc:
                        status = f"Error: {exc}"
                    _draw_restore()
                    stdscr.getch()
                    break

            _draw_restore()

    curses.wrapper(_wrapper)
    return restored_files


# ---------------------------------------------------------------------------
# Curated pick TUI
# ---------------------------------------------------------------------------


def _show_compose_parent_rc_warnings(stdscr, messages: list[str]) -> None:
    """Show multi-line compose parent-rc warnings; wait for a keypress."""
    stdscr.clear()
    try:
        stdscr.border()
    except curses.error:
        pass
    h, w = stdscr.getmaxyx()
    row = 2
    title = "Compose: parent rc may not load fragments"
    try:
        stdscr.addstr(1, 2, title[: max(0, w - 4)])
    except curses.error:
        pass
    for msg in messages:
        for line in msg.splitlines():
            if row >= h - 3:
                try:
                    stdscr.addstr(h - 3, 2, "… (truncated; full text on stderr)")
                except curses.error:
                    pass
                row = h - 2
                break
            try:
                stdscr.addstr(row, 2, line[: max(0, w - 4)])
            except curses.error:
                pass
            row += 1
        row += 1
        if row >= h - 3:
            break
    try:
        stdscr.addstr(h - 2, 2, "Press any key to continue")
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()


def display_compose_pick_tui(family: str) -> list[str]:
    """Interactive TUI for selecting and installing compose files.

    Shows available compose files with summaries. Selected files are
    symlinked into the user's home directory and the registry is updated.

    Parameters
    ----------
    family : str
        Shell family (zsh, bash, tcsh).

    Returns
    -------
    list[str]
        Absolute paths of installed files (empty if cancelled).
    """
    from .compose import compose_parent_rc_warnings, install_compose_files, list_compose_files

    files = list_compose_files(family)
    if not files:
        return []

    # Valid entries first (list_compose_files order); mark invalid for visibility
    labels = [
        (
            f"{cf.dest_basename}  {cf.summary[:50]}"
            if cf.summary_valid
            else f"[!] {cf.dest_basename}  {cf.summary[:42]}"
        )
        for cf in files
    ]
    state = ChecklistState(items=labels, checked=[False] * len(files))

    installed: list[str] = []

    def _wrapper(stdscr):
        nonlocal installed
        curses.curs_set(0)
        status = ""

        def _draw():
            n_sel = sum(state.checked)
            extra = [
                f"Family: {family}    Files: {n_sel} selected / {len(files)} total",
            ]
            if status:
                extra.append(status)
            _draw_checklist(
                stdscr,
                state,
                title="shellenv: select compose files to install",
                subtitle="Space: toggle  a: all  n: none  Enter: install  q: quit",
                footer="q=quit  Space=toggle  a=all  n=none  Enter=install",
                extra_lines=extra,
            )

        def _confirm(prompt: str) -> bool:
            stdscr.clear()
            stdscr.border()
            try:
                stdscr.addstr(2, 2, prompt)
                stdscr.addstr(4, 2, "y=yes  n=no")
            except curses.error:
                pass
            stdscr.refresh()
            while True:
                ch = stdscr.getch()
                if ch in (ord("y"), ord("Y")):
                    return True
                if ch in (ord("n"), ord("N")):
                    return False

        _draw()
        while True:
            ch = stdscr.getch()
            h, w = stdscr.getmaxyx()
            display_lines = h - 10

            _checklist_nav(ch, state, display_lines)

            if ch in (ord("q"), ord("Q")):
                break

            if ch in (curses.KEY_ENTER, 10, 13):
                selected_files = [files[i] for i, c in enumerate(state.checked) if c]
                if not selected_files:
                    status = "No files selected"
                    _draw()
                    continue

                if _confirm(f"Install {len(selected_files)} file(s) to home directory?"):
                    try:
                        installed = install_compose_files(selected_files)
                        status = f"Installed {len(installed)} file(s)"
                        warns = compose_parent_rc_warnings(selected_files, family=family)
                        for w in warns:
                            print(w, file=sys.stderr)
                        if warns:
                            _show_compose_parent_rc_warnings(stdscr, warns)
                    except Exception as exc:
                        status = f"Error: {exc}"
                    _draw()
                    stdscr.getch()
                    break

            _draw()

    curses.wrapper(_wrapper)
    return installed


# ---------------------------------------------------------------------------
# Config editor helpers (testable without curses)
# ---------------------------------------------------------------------------


def validate_editor_config(path: str | Path) -> list[str]:
    """Validate a TOML config file against the schema.

    Parameters
    ----------
    path : str or Path
        Path to a TOML config file (e.g. the user config after editing).

    Returns
    -------
    list[str]
        Error messages.  Empty means the file is valid.  Includes TOML
        parse errors as well as schema violations.
    """
    import tomllib

    from .config import validate_config

    p = Path(path)
    if not p.exists():
        return ["file does not exist"]
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        return [f"invalid TOML: {exc}"]
    if not isinstance(data, dict):
        return ["config must be a TOML table"]
    return validate_config(data)


# ---------------------------------------------------------------------------
# Config TUI
# ---------------------------------------------------------------------------


def _draw_config_screen(
    stdscr, keys: list[str], values: dict[str, Any], selected: int, top: int, status: str
) -> None:
    """Draw the config editor main screen."""
    from .config import CONFIG_SCHEMA

    stdscr.clear()
    stdscr.border()
    h, w = stdscr.getmaxyx()
    stdscr.addstr(1, 2, "shellenv: configuration editor")
    stdscr.addstr(2, 2, "Up/Down: navigate  Enter: edit  e: $EDITOR  r: reset  q: quit")
    header_y = 4
    col_val = min(32, w // 2)
    stdscr.addstr(header_y, 2, f"{'Key':<{col_val}} Value")
    display_lines = h - (header_y + 4)

    for i in range(display_lines):
        idx = top + i
        y = header_y + 1 + i
        if idx >= len(keys):
            break
        key = keys[idx]
        meta = CONFIG_SCHEMA[key]
        val_repr = repr(values.get(key, meta.default))
        line = f"{key:<{col_val}} {val_repr}"
        line = line[: w - 4]
        try:
            attr = curses.A_REVERSE if idx == selected else 0
            stdscr.addstr(y, 2, line, attr)
        except curses.error:
            pass

    if status:
        try:
            stdscr.addstr(h - 3, 2, status[: w - 4])
        except curses.error:
            pass
    stdscr.addstr(h - 2, 2, "q=quit  Enter=edit  e=$EDITOR  r=reset")
    stdscr.refresh()


def _prompt_value(stdscr, key: str, current: Any) -> str | None:
    """Show a one-line prompt for a new value; return the string or None on escape."""
    h, w = stdscr.getmaxyx()
    prompt = f"New value for {key} (current: {current!r}): "
    try:
        stdscr.addstr(h - 3, 2, " " * (w - 4))
        stdscr.addstr(h - 3, 2, prompt[: w - 4])
        stdscr.refresh()
    except curses.error:
        pass
    curses.echo()
    curses.curs_set(1)
    try:
        raw = stdscr.getstr(h - 3, 2 + len(prompt), w - 4 - len(prompt))
    except curses.error:
        raw = None
    curses.noecho()
    curses.curs_set(0)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace").strip()


def _editor_flow(stdscr) -> str:
    """Open user config in $EDITOR, validate on return.

    Returns a status message describing the outcome.
    """
    from .config import save_config, user_config_path

    path = user_config_path()
    # ensure file exists so editor has something to open
    if not path.exists():
        save_config(path, {})

    backup = path.read_text(encoding="utf8")

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    curses.endwin()
    subprocess.run([editor, str(path)])

    errors = validate_editor_config(path)
    if errors:
        # restore backup
        path.write_text(backup, encoding="utf8")
        return f"Reverted: {errors[0]}"

    return "Config saved"


def _handle_config_edit(stdscr, key: str, values: dict[str, Any]) -> str:
    """Prompt for a new value and apply it.

    Returns
    -------
    str
        Status message for the user.
    """
    from .config import CONFIG_SCHEMA, coerce_value, config_set

    meta = CONFIG_SCHEMA[key]
    current = values.get(key, meta.default)
    raw = _prompt_value(stdscr, key, current)
    if raw is None or raw == "":
        return "Edit cancelled"
    try:
        if meta.value_type == "list_of_strings":
            val = [s.strip() for s in raw.split(",") if s.strip()]
        else:
            val = coerce_value(raw, meta.value_type)
        config_set(key, val)
        return f"Set {key}"
    except (ValueError, KeyError) as exc:
        return f"Error: {exc}"


def _handle_config_reset(key: str) -> str:
    """Reset a key and return a status string."""
    from .config import config_reset

    try:
        config_reset(key)
        return f"Reset {key}"
    except KeyError as exc:
        return f"Error: {exc}"


def _config_nav(ch: int, selected: int, top: int, n_keys: int, display_lines: int):
    """Process navigation keys, returning updated (selected, top)."""
    if ch in (curses.KEY_DOWN, ord("j")) and selected < n_keys - 1:
        selected += 1
        if selected >= top + display_lines:
            top += 1
    elif ch in (curses.KEY_UP, ord("k")) and selected > 0:
        selected -= 1
        if selected < top:
            top = max(0, top - 1)
    return selected, top


def display_config_tui() -> None:
    """Interactive TUI for viewing and editing config key/value pairs.

    Controls
    --------
    - Up/Down (j/k) : navigate keys
    - Enter : edit the selected key inline
    - e : open user config in ``$EDITOR`` (validated on save)
    - r : reset selected key to default
    - q : quit
    """
    from .config import CONFIG_SCHEMA, config_show

    keys = sorted(CONFIG_SCHEMA)

    def _wrapper(stdscr):
        curses.curs_set(0)
        selected = 0
        top = 0
        status = ""
        values = config_show()
        _draw_config_screen(stdscr, keys, values, selected, top, status)

        while True:
            ch = stdscr.getch()
            h, _ = stdscr.getmaxyx()
            display_lines = h - 8

            if ch in (ord("q"), ord("Q")):
                break

            selected, top = _config_nav(ch, selected, top, len(keys), display_lines)

            if ch in (curses.KEY_ENTER, 10, 13):
                status = _handle_config_edit(stdscr, keys[selected], values)
                values = config_show()
            elif ch in (ord("e"), ord("E")):
                status = _editor_flow(stdscr)
                values = config_show()
            elif ch in (ord("r"), ord("R")):
                status = _handle_config_reset(keys[selected])
                values = config_show()

            _draw_config_screen(stdscr, keys, values, selected, top, status)

    curses.wrapper(_wrapper)
