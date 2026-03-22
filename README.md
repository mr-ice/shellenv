# shellenv

shellenv is a lightweight toolkit to discover, trace, and analyze shell
startup files (bash, zsh, tcsh) so you can find slow or surprising startup
hooks. The project includes safe mock traces and a simple TUI for exploration.

## Quickstart

Install into your environment (editable for development):

```bash
python -m pip install -e .
```

Run the CLI (example):

```bash
shellenv detect
shellenv discover --family bash --modes
shellenv trace --family bash --mode ln --dry-run
shellenv trace --family bash --mode login_noninteractive --tui
```

Force the safer shell-level tracer (useful on macOS/CI):

```bash
shellenv discover --use-shell-trace --modes
```

Clear discovery cache:

```bash
shellenv discover --refresh-cache
```

## Logging

Use `--log-level` to control verbosity (applies to all commands):

```bash
shellenv --log-level DEBUG compose list
```

Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: WARNING).

## Environment variables

- `SHELLENV_MOCK_TRACE_DIR`: directory of fixture traces used by tests and
  to run the shell-level tracer in mock mode. Point this to
  `tests/fixtures/traces` to reproduce CI/test behavior.
- `SHELLENV_USE_SHELL_TRACE`: set to `1`, `true`, or `yes` to force the
  shell-level tracer instead of system tracers like `strace`.
- `SHELLENV_CACHE_DIR`: overrides the cache directory used by discovery.
- `SHELLENV_BACKUP_DIR`: overrides the backup archive directory
  (default `~/.cache/shellenv/backups`).

## CLI highlights

- `detect` — detect current and intended shell and family. See
  [src/shellenv/detect_shell.py](src/shellenv/detect_shell.py)
- `discover` — discover candidate startup files (per-mode or union). Flags:
  `--family`, `--shell-path`, `--use-shell-trace`, `--refresh-cache`,
  `--modes`, `--mode` (li/ln/ni/nn or full names, repeatable). See [src/shellenv/discover.py](src/shellenv/discover.py).
- `trace` — run a shell-level trace and summarize per-file timing. Flags:
  `--family`, `--shell-path`, `--mode` (li/ln/ni/nn), `--dry-run`, `--output-file`,
  `--threshold-secs`, `--threshold-percent`, `--tui`. Core tracing/parsing is in
  [src/shellenv/trace.py](src/shellenv/trace.py).
- `backup` — back up discovered startup files to a tar.gz archive. Flags:
  `--family`, `--include`, `--exclude`, `--tui`.
- `archive` — back up startup files and remove originals. Flags:
  `--family`, `--include`, `--exclude`, `--yes`, `--tui`.
- `restore` — restore files from a backup archive. Flags:
  `--archive`, `--include`, `--exclude`, `--force`, `--yes`, `--tui`.
- `list-backups` — list available backup archives with timestamps and 
  file contents.
- `compose` — pick and install optional shell init files from compose paths.
  Subcommands: `list`, `pick` (with `--tui` for interactive selection).

## Testing

Run the test suite with the correct PYTHONPATH (the Makefile target wraps
this for convenience):

```bash
make test
# or
PYTHONPATH=src pytest -q
```

The tests use mock trace fixtures under `tests/fixtures/traces`; to run the
discovery/trace code paths using these fixtures set `SHELLENV_MOCK_TRACE_DIR`.

## Development notes

- Parsers: `src/shellenv/trace.py` contains parsers for bash, zsh, tcsh and
  a generic fallback. Improve path normalization and timestamp extraction
  there when adding new fixtures.
- Discovery: `src/shellenv/discover.py` prefers system tracers where
  available but falls back to the safer shell-level tracer which honors the
  mock fixtures. The cache directory defaults to `~/.cache/shellenv` but
  can be overridden with `SHELLENV_CACHE_DIR`.
- TUI: a simple curses UI lives in `src/shellenv/tui.py`.

# shellenv

shellenv is a tool to manage shell
startup files (login/profile/rc files), back them up, and include compose startup files from directories given in the config.

Current implemented features (prototype)

- `detect`: determine current/login shell and intended shell using:
  - login shell from the passwd entry
  - `$SHELL` environment variable
  - parent process name
  - optional CLI override `--shell`

- `discover`: best-effort discovery of startup files used by shell
  families. Defaults to shell-level tracing (portable). Optional
  `SHELLENV_USE_SYSTEM_TRACER=1` uses `strace` on Linux when available.
  Use `--modes` to list files
  for four invocation modes: `login_interactive`, `login_noninteractive`,
  `nonlogin_interactive`, `nonlogin_noninteractive`.

- `trace`: run a non-privileged shell-level trace to capture which
  startup files are sourced and approximate time spent in each file.
  - Supports `bash`, `zsh`, and `tcsh` families.
  - Uses `BASH_XTRACEFD` + `PS4` for `bash` to capture timestamps; a patched
    bash (`patches/bash-sourcetrace.patch`, `SHELLENV_BASH_PATH`) adds
    per-file `<sourcetrace>` lines like zsh’s `SOURCE_TRACE`.
  - Uses `-x` capture of stderr for `zsh`/`tcsh` and best-effort parsing.
  - Analyze results to compute per-file duration and percent of total.
  - Thresholds: `--threshold-secs` and `--threshold-percent` to flag slow files.
  - `--dry-run` prints the command without executing.
  - `--output-file` saves raw trace output for inspection.
  - `--tui` opens a minimal curses UI to inspect flagged files.

## Configuration

Global config: `/etc/shellenv.toml` (optional)
User config: `~/.shellenv.toml` (optional)

Generate a full site-wide defaults template (all keys):

```bash
shellenv config init-global --path ./config/shellenv.global.defaults.toml
```

There is also a checked-in template at
`config/shellenv.global.defaults.toml`.

Config keys of interest (example):

```toml
[trace]
threshold_secs = 0.5
threshold_percent = 10.0
```

User level config overrides global ones.

### CLI config commands

View all config keys and their current (merged) values:

```bash
shellenv config show
shellenv config show compose.paths   # show just one key's value
```

Get a single key:

```bash
shellenv config get trace.threshold_secs
# None
```

Set a value in the user config (`~/.shellenv.toml`):

```bash
# float
shellenv config set trace.threshold_secs 0.05

# string
shellenv config set repo.url https://example.com/dotfiles.git

# clear a nullable key back to null
shellenv config set trace.threshold_secs null

# list of strings (space-separated)
shellenv config set compose.paths /opt/shell-extras /usr/local/etc/env

# append to an existing list instead of replacing it
shellenv config set compose.paths /another/path --append
```

Reset a key (removes it from the user config, reverting to the
global or default value):

```bash
shellenv config reset trace.threshold_percent
```

Open the user config in `$EDITOR` with live validation (invalid
edits are reverted automatically):

```bash
shellenv config --tui
```

## Backup, archive, and restore

Back up discovered startup files to a tar.gz archive:

```bash
shellenv backup
shellenv backup --family zsh
shellenv backup --include ".zshrc" --include ".zprofile"
shellenv backup --exclude ".bash*"
```

Archive (backup + delete originals) — prompts for confirmation unless
`--yes` is passed:

```bash
shellenv archive --family bash
shellenv archive --family bash --yes
```

List available backup archives:

```bash
shellenv list-backups
```

Restore from the most recent archive (skips existing files by default):

```bash
shellenv restore
shellenv restore --force          # overwrite existing files
shellenv restore --archive 20260215   # match archive by substring
shellenv restore --include ".zshrc" --exclude ".zprofile"
shellenv restore --yes --force    # no confirmation, overwrite
```

Use `--tui` for interactive file selection (shows all shell families,
active family highlighted and pre-checked):

```bash
shellenv backup --tui
shellenv archive --tui
shellenv restore --tui
```

Archives are stored in `~/.cache/shellenv/backups/` by default.
Override with the `SHELLENV_BACKUP_DIR` environment variable.

Safety and notes

- The tracer runs the user's shell and will execute startup files. By
  default the invocation uses `-c true` to exit after startup, but the
  startup files are still executed — run on a safe/test account if you
  are worried about side-effects.
- The syscall-level tracing (strace/eBPF/DTrace) is not used by default
  because it can require privileges. The shell-level approach is
  portable and non-privileged and typically identifies slow shell
  plugins and initialization commands which are the primary operator
  complaints.

Development / usage

Install test deps and run tests:

```bash
python -m pip install -U pytest
make test
```

Basic CLI examples

```bash
# detect
PYTHONPATH=src python -m shellenv.cli detect

# discover (per-mode)
PYTHONPATH=src python -m shellenv.cli discover --family bash --modes

# run a trace and print a summary
PYTHONPATH=src python -m shellenv.cli trace --family bash --mode login_noninteractive --threshold-secs 0.05

# run trace and open curses TUI
PYTHONPATH=src python -m shellenv.cli trace --family bash --mode login_noninteractive --threshold-secs 0.05 --tui

# dry-run to view command
PYTHONPATH=src python -m shellenv.cli trace --family zsh --mode login_noninteractive --dry-run
```

Next features to implement

- Repo init/install for compose startup files.
- Additional shell-family improvements and safer tracer mocks for CI.
