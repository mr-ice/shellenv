"""Shell startup tracing (bash/zsh/tcsh) and parser utilities.

This module provides a best-effort, non-privileged tracer that runs a
specified shell in one of the invocation modes and collects a textual
trace. The parser computes per-startup-file timing information.

Notes
-----
- For `bash` we use `BASH_XTRACEFD` to redirect xtrace to a file and set
  `PS4` to include timestamps and source file info.  A patched bash (see
  `patches/bash-sourcetrace.patch`) emits zsh-like per-file `<sourcetrace>`
  lines into the same stream.
- For `tcsh` we use a patched tcsh with `TCSH_XTRACEFD` (see patches/README.md);
  when available, xtrace is redirected to a fd with timestamped lines.
- For `zsh` we run with `-o SOURCE_TRACE -x`, set `PS4=+%N:%i> ` in env,
  and capture stderr; parsing uses the default PS4 format.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileTrace:
    """Represents timing info for a single startup file."""

    path: str
    first_ts: float
    last_ts: float
    commands: int

    @property
    def duration(self) -> float:
        """Return duration in seconds for this file's execution."""
        return self.last_ts - self.first_ts


def _timestamp_now() -> float:
    """Return current timestamp as float seconds."""
    return time.time()


def get_bash_for_tracing(shell_path: str | None = None) -> str | None:
    """Resolve bash path for tracing. Prefer patched bash with source-trace lines.

    Checks (in order):
    1. shell_path if provided and executable
    2. SHELLENV_BASH_PATH (patched bash from patches/bash-sourcetrace.patch)
    3. bash-src/bash if present (local build from project root)
    4. shutil.which("bash") as fallback (no per-file source trace lines)
    """
    import shutil

    if shell_path and os.path.isfile(shell_path) and os.access(shell_path, os.X_OK):
        return shell_path
    env_path = os.environ.get("SHELLENV_BASH_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    for base in (Path(__file__).resolve().parents[2], Path.cwd()):
        candidate = base / "bash-src" / "bash"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("bash")


def get_tcsh_for_tracing(shell_path: str | None = None) -> str | None:
    """Resolve tcsh path for tracing. Prefer patched tcsh with TCSH_XTRACEFD support.

    Checks (in order):
    1. shell_path if provided and executable
    2. SHELLENV_TCSH_PATH (patched tcsh built from patches/README.md)
    3. tcsh-src/tcsh if present (local build from project root)
    4. shutil.which("tcsh") as fallback (may not support TCSH_XTRACEFD)
    """
    import shutil

    if shell_path and os.path.isfile(shell_path) and os.access(shell_path, os.X_OK):
        return shell_path
    env_path = os.environ.get("SHELLENV_TCSH_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    # tcsh-src/tcsh relative to project (shellenv root or cwd)
    for base in (Path(__file__).resolve().parents[2], Path.cwd()):
        candidate = base / "tcsh-src" / "tcsh"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("tcsh")


def run_shell_trace(
    family: str,
    shell_path: str | None = None,
    args: list[str] | None = None,
    timeout: int = 15,
    dry_run: bool = False,
    output_file: str | None = None,
) -> str:
    """Run a shell in tracing mode and return the raw trace text.

    This is best-effort and conservative: it avoids privileged operations
    and attempts to limit side-effects by running the shell with a
    command that immediately exits after startup.
    """
    family = family.lower()
    if family == "bash":
        shell = shell_path or get_bash_for_tracing(None) or "bash"
    elif family == "zsh":
        shell = shell_path or "zsh"
    else:
        shell = shell_path or get_tcsh_for_tracing(shell_path) or "tcsh"

    # Build basic invocation flags: prefer login noninteractive by default
    if args is None:
        args = ["-l", "-c", "true"]

    # For bash: use BASH_XTRACEFD to redirect xtrace to a temp file and
    # set PS4 to include a timestamp and the ${BASH_SOURCE}:${LINENO} info.
    # Support mock traces for tests: if SHELLENV_MOCK_TRACE_DIR is set
    # try to load a fixture file named {family}_{mode}.txt and return it.
    mock_dir = os.environ.get("SHELLENV_MOCK_TRACE_DIR")
    if mock_dir:
        # derive mode from args: login vs nonlogin, interactive vs noninteractive
        _args = args or []
        login = "login" if any(a == "-l" for a in _args) else "nonlogin"
        interactive = "interactive" if any(a == "-i" for a in _args) else "noninteractive"
        mode_id = f"{login}_{interactive}"
        fname = os.path.join(mock_dir, f"{family}_{mode_id}.txt")
        if os.path.exists(fname):
            try:
                with open(fname, encoding="utf8", errors="ignore") as fh:
                    return fh.read()
            except Exception:
                pass

    if family == "bash":
        tf = tempfile.NamedTemporaryFile(delete=False)
        tf.close()
        fd = os.open(tf.name, os.O_WRONLY | os.O_APPEND)
        env = os.environ.copy()
        env["BASH_XTRACEFD"] = str(fd)
        # Use $EPOCHREALTIME when available; fallback to date via PS4
        ps4 = "+$(date +%s.%N) ${BASH_SOURCE}:${LINENO} "
        env["PS4"] = ps4
        cmd = [shell] + ["-x"] + args
        try:
            # pass the open fd into the child
            if dry_run:
                # return the would-be command
                os.close(fd)
                return "DRYRUN: " + " ".join(shlex.quote(c) for c in cmd)
            subprocess.run(
                cmd,
                env=env,
                pass_fds=(fd,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
        # read file
        with open(tf.name, encoding="utf8", errors="ignore") as fh:
            txt = fh.read()
        if output_file:
            with open(output_file, "w", encoding="utf8") as ofh:
                ofh.write(txt)
        try:
            os.unlink(tf.name)
        except Exception:
            pass
        return txt

    # For zsh and tcsh: run with -x and capture stderr. Include PS4-like
    # prefix where supported via environment.
    if family == "zsh":
        env = os.environ.copy()
        # Use zsh default PS4 (+%N:%i> ) so user's .zshenv can't override it.
        # %N = script/function name, %i = line number.
        env["PS4"] = "+%N:%i> "
        # SOURCE_TRACE prints each file as it's loaded; needed for proper discovery.
        cmd = [shell, "-o", "SOURCE_TRACE", "-x"] + args
        if dry_run:
            return "DRYRUN: " + " ".join(shlex.quote(c) for c in cmd)
        proc = subprocess.run(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        txt = proc.stderr or ""
        if output_file and txt:
            with open(output_file, "w", encoding="utf8") as ofh:
                ofh.write(txt)
        return txt

    # tcsh: use TCSH_XTRACEFD when we have patched tcsh (same approach as bash).
    # Patched tcsh writes timestamped lines to the fd; unpatched tcsh ignores it.
    if family in ("tcsh", "csh"):
        tf = tempfile.NamedTemporaryFile(delete=False)
        tf.close()
        fd = os.open(tf.name, os.O_WRONLY | os.O_APPEND)
        env = os.environ.copy()
        env["TCSH_XTRACEFD"] = str(fd)
        cmd = [shell, "-x"] + args
        try:
            if dry_run:
                os.close(fd)
                return "DRYRUN: " + " ".join(shlex.quote(c) for c in cmd)
            subprocess.run(
                cmd,
                env=env,
                pass_fds=(fd,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
        with open(tf.name, encoding="utf8", errors="ignore") as fh:
            txt = fh.read()
        if output_file and txt:
            with open(output_file, "w", encoding="utf8") as ofh:
                ofh.write(txt)
        try:
            os.unlink(tf.name)
        except Exception:
            pass
        # If trace is empty (unpatched tcsh ignores TCSH_XTRACEFD), fall back to stderr
        if not txt.strip():
            proc = subprocess.run(
                cmd[:1] + ["-x"] + cmd[2:],
                env={k: v for k, v in os.environ.items() if k != "TCSH_XTRACEFD"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            txt = proc.stderr or ""
            if output_file and txt:
                with open(output_file, "w", encoding="utf8") as ofh:
                    ofh.write(txt)
        return txt or ""

    # fallback: run shell and capture stderr
    cmd = [shell] + args
    if dry_run:
        return "DRYRUN: " + " ".join(shlex.quote(c) for c in cmd)
    proc = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout
    )
    txt = proc.stderr or ""
    if output_file and txt:
        with open(output_file, "w", encoding="utf8") as ofh:
            ofh.write(txt)
    return txt


def parse_bash_trace(trace_text: str) -> dict[str, FileTrace]:
    """Parse bash xtrace output produced with PS4 '+$(date +%s.%N) ${BASH_SOURCE}:${LINENO} '.

    Patched bash (bash-sourcetrace) also emits file-entry lines of the form
    ``+0.000000 /path/to/file:1 <sourcetrace>`` into the xtrace stream.

    Returns a mapping from file path to FileTrace.
    """
    # Example trace line begins with: +1613341234.123456 /home/user/.bashrc:12 command
    pat = re.compile(r"^\+([0-9]+\.[0-9]+)\s+(.+?):(\d+)\s+(.*)$")
    files: dict[str, FileTrace] = {}
    home = os.path.expanduser("~")

    def _normalize_src_path(src_path: str) -> str:
        """Normalize a source path from bash trace.

        - expanduser (~)
        - if absolute, normalize
        - if relative and looks like a home-dotfile, join with $HOME
        - leave other tokens unchanged
        """
        if not src_path:
            return src_path
        src_path = src_path.strip()
        # ignore special markers
        if src_path in ("0", "bash"):
            return src_path
        # expand ~
        src_path = os.path.expanduser(src_path)
        # absolute path
        if os.path.isabs(src_path):
            return os.path.normpath(src_path)
        # relative dotfile (e.g., .bashrc) -> assume under $HOME
        if src_path.startswith(".") or src_path.startswith("./"):
            return os.path.normpath(os.path.join(home, src_path))
        # otherwise return as-is
        return src_path

    for line in trace_text.splitlines():
        m = pat.match(line)
        if not m:
            continue
        ts = float(m.group(1))
        src = m.group(2)
        # normalize source: if $BASH_SOURCE is '0' or 'bash' use special handling
        src_path = _normalize_src_path(src)
        # Many shells will report relative or absolute paths; keep as-is
        if src_path not in files:
            files[src_path] = FileTrace(path=src_path, first_ts=ts, last_ts=ts, commands=1)
        else:
            ft = files[src_path]
            ft.last_ts = ts
            ft.commands += 1
    return files


def _expand_trace_path(path: str) -> str:
    """Expand ~ and $HOME in a path from trace output."""
    path = path.strip().strip("'\"")
    path = os.path.expanduser(path)
    # expand $HOME / ${HOME} when expanduser didn't handle it
    home = os.path.expanduser("~")
    path = path.replace("$HOME", home).replace("${HOME}", home)
    return path


def parse_zsh_trace(trace_text: str) -> dict[str, FileTrace]:
    """Parse zsh trace output with best-effort handling of `source` and PS4 timestamps."""
    files: dict[str, FileTrace] = {}
    ts_pat = re.compile(r"^\+([0-9]+\.[0-9]+)\s+(.*)$")
    source_pat = re.compile(r"(?:^|\s)(?:source|\.)\s+([^\s\"']+|\"[^\"]*\"|'[^']*')")
    lines = trace_text.splitlines()
    synthetic_start = time.time()
    delta = 0.000001
    next_ts = synthetic_start

    for line in lines:
        m = ts_pat.match(line)
        if m:
            ts = float(m.group(1))
            rest = m.group(2)
        else:
            # assign synthetic timestamp and treat the whole line as rest
            ts = next_ts
            next_ts += delta
            rest = line

        # Prefer explicit source target (source/. file) over PS4 prefix file.
        # Example: "+.../.zshlib/all:4> source .../.zshlib/mkcd" should
        # attribute to mkcd, not all.
        m2 = source_pat.search(rest)
        if m2:
            src_path = _expand_trace_path(m2.group(1))
        else:
            # fallback to explicit path token (often PS4 file:line prefix)
            p = re.search(r"(/[^\s:]+)[:]?\d*", rest)
            if p:
                src_path = _expand_trace_path(p.group(1))
            else:
                # skip lines without clear source
                continue

        if src_path.startswith("."):
            src_path = os.path.normpath(os.path.join(os.path.expanduser("~"), src_path))

        if src_path not in files:
            files[src_path] = FileTrace(path=src_path, first_ts=ts, last_ts=ts, commands=1)
        else:
            ft = files[src_path]
            ft.last_ts = ts
            ft.commands += 1

    return files


def parse_tcsh_trace(trace_text: str) -> dict[str, FileTrace]:
    """Parse tcsh traces by looking for `source` and timestamped lines.

    Patched tcsh emits ``+timestamp /path <sourcetrace>`` when a file is
    opened for sourcing (see ``tcsh-sourcetrace.patch``).

    This parser is best-effort: it extracts source file tokens and assigns
    synthetic timestamps when explicit timestamps are absent.
    """
    files: dict[str, FileTrace] = {}
    ts_pat = re.compile(r"^\+([0-9]+\.[0-9]+)\s+(.*)$")
    sourcetrace_pat = re.compile(r"^\+([0-9]+\.[0-9]+)\s+(/[^\s]+)\s+<sourcetrace>\s*$")
    source_pat = re.compile(r"(?:^|\s)(?:source|\.)\s+([^\s\"']+|\"[^\"]*\"|'[^']*')")
    lines = trace_text.splitlines()
    synthetic_start = time.time()
    delta = 0.000001
    next_ts = synthetic_start

    for line in lines:
        mst = sourcetrace_pat.match(line)
        if mst:
            ts = float(mst.group(1))
            src_path = _expand_trace_path(mst.group(2))
            if src_path.startswith("."):
                src_path = os.path.normpath(os.path.join(os.path.expanduser("~"), src_path))
            if src_path not in files:
                files[src_path] = FileTrace(path=src_path, first_ts=ts, last_ts=ts, commands=1)
            else:
                ft = files[src_path]
                ft.last_ts = ts
                ft.commands += 1
            continue

        m = ts_pat.match(line)
        if m:
            ts = float(m.group(1))
            rest = m.group(2)
        else:
            ts = next_ts
            next_ts += delta
            rest = line

        m2 = source_pat.search(rest)
        if m2:
            src_path = _expand_trace_path(m2.group(1))
        else:
            p = re.search(r"(/[^\s:]+)[:]?\d*", rest)
            if p:
                src_path = _expand_trace_path(p.group(1))
            else:
                continue

        if src_path.startswith("."):
            src_path = os.path.normpath(os.path.join(os.path.expanduser("~"), src_path))

        if src_path not in files:
            files[src_path] = FileTrace(path=src_path, first_ts=ts, last_ts=ts, commands=1)
        else:
            ft = files[src_path]
            ft.last_ts = ts
            ft.commands += 1

    return files


def parse_generic_trace(trace_text: str) -> dict[str, FileTrace]:
    """Best-effort parser for zsh/tcsh - looks for timestamp prefixes and source/file patterns.

    This will search for '+TIMESTAMP ' prefixes and then attempt to
    extract a path-like token from the line.
    """
    ts_pat = re.compile(r"^\+([0-9]+\.[0-9]+)\s+(.*)$")
    path_pat = re.compile(r"(/[^\s:]+)[:]?\d*")
    # match 'source filename' or '. filename'
    source_pat = re.compile(r"(?:^|\s)(?:source|\.)\s+([^\s]+)")
    files: dict[str, FileTrace] = {}
    # If no timestamped lines are present, assign incremental synthetic timestamps
    lines = trace_text.splitlines()
    synthetic_start = time.time()
    delta = 0.000001
    next_ts = synthetic_start

    for line in lines:
        m = ts_pat.match(line)
        if m:
            ts = float(m.group(1))
            rest = m.group(2)
        else:
            # assign a synthetic increasing timestamp
            ts = next_ts
            next_ts += delta
            rest = line

        p = path_pat.search(rest)
        if p:
            src_path = p.group(1)
        else:
            m2 = source_pat.search(rest)
            if m2:
                src_path = m2.group(1)
            else:
                # try to find a bare filename token
                tok = rest.strip().split()
                if tok:
                    candidate = tok[0]
                    if candidate.startswith("./") or candidate.startswith("/") or "." in candidate:
                        src_path = candidate
                    else:
                        continue
                else:
                    continue
        # normalize discovered path: expand ~ and resolve dotfiles to $HOME
        src_path = os.path.expanduser(src_path)
        if not os.path.isabs(src_path) and src_path.startswith("."):
            src_path = os.path.normpath(os.path.join(os.path.expanduser("~"), src_path))

        if src_path not in files:
            files[src_path] = FileTrace(path=src_path, first_ts=ts, last_ts=ts, commands=1)
        else:
            ft = files[src_path]
            ft.last_ts = ts
            ft.commands += 1
    return files


def parse_trace(trace_text: str, family: str = "bash") -> list[FileTrace]:
    """Parse trace output and return list of FileTrace sorted by duration desc."""
    family = (family or "bash").lower()
    if family == "bash":
        files = parse_bash_trace(trace_text)
    elif family == "zsh":
        files = parse_zsh_trace(trace_text)
    elif family in ("tcsh", "csh"):
        files = parse_tcsh_trace(trace_text)
    else:
        files = parse_generic_trace(trace_text)

    out = list(files.values())
    out.sort(key=lambda f: f.duration, reverse=True)
    return out


def collect_startup_file_traces(
    family: str,
    shell_path: str | None = None,
    args: list[str] | None = None,
    *,
    dry_run: bool = False,
    output_file: str | None = None,
    timeout: int = 15,
) -> list[FileTrace] | str:
    """Collect startup trace text and parse it into per-file records.

    Returns parsed traces, or a DRYRUN string when ``dry_run`` is true.
    """
    raw = run_shell_trace(
        family,
        shell_path=shell_path,
        args=args,
        timeout=timeout,
        dry_run=dry_run,
        output_file=output_file,
    )
    if isinstance(raw, str) and raw.startswith("DRYRUN:"):
        return raw
    return parse_trace(raw, family=family)


def analyze_traces(
    traces: list[FileTrace],
    threshold_secs: float | None = None,
    threshold_percent: float | None = None,
):
    """Analyze traces and mark files exceeding thresholds.

    Returns a list of dicts with keys: file, duration, commands, percent,
    flagged (bool), reasons (list).
    """
    total = sum(max(0.0, t.duration) for t in traces)
    out = []
    for t in traces:
        dur = max(0.0, t.duration)
        percent = (dur / total * 100.0) if total > 0 else 0.0
        reasons = []
        flagged = False
        if threshold_secs is not None and dur >= threshold_secs:
            flagged = True
            reasons.append(f">={threshold_secs:.3f}s")
        if threshold_percent is not None and percent >= threshold_percent:
            flagged = True
            reasons.append(f">={threshold_percent:.1f}%")
        out.append(
            {
                "file": t.path,
                "duration": dur,
                "commands": t.commands,
                "percent": percent,
                "flagged": flagged,
                "reasons": reasons,
            }
        )
    # sort by duration desc
    out.sort(key=lambda x: x["duration"], reverse=True)
    return {"total": total, "items": out}
