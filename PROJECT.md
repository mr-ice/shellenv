# shellenv

shellenv is a tool for operators to control shell environment startup files (bash, zsh, tcsh): discover what runs, trace cost, back up and restore, optionally pull init files from a repo, and **compose** extra snippets from configured directories.

This document is the product spec. For day-to-day CLI usage and developer commands, see `README.md`.

## Configuration

| Layer | Path | Notes |
| --- | --- | --- |
| Site / global | `/etc/shellenv.toml` | Optional. |
| User | `~/.shellenv.toml` | Overrides global; list keys such as `compose.paths` append to global when merged. |

- **Site template**: `config/shellenv.global.defaults.toml` in the repo is a full commented template (regenerate with `shellenv config init-global --path …`).
- **Override global path (installs, CI, pytest)**: set **`SHELLENV_GLOBAL_CONFIG_PATH`** to another file instead of `/etc/shellenv.toml`.

Relevant schema keys include `trace.*`, `repo.*`, and `compose.*` (`paths`, `shell_rc_files`, `allow_non_repo`). See `src/shellenv/config.py` (`CONFIG_SCHEMA`).

## Compose (feature summary)

Optional init fragments live in directories listed in `compose.paths`. Files must match `{rc_base}-{tag}` (e.g. `zshrc-fzf`); the first comment line is treated as a one-line description. Selected files are installed into the home directory (e.g. `~/.zshrc-fzf`) and tracked in a registry under the cache dir.

- **Git policy (current implementation)**: by default each path must be a git worktree on `main` or `master` with a **clean** working tree. Set **`compose.allow_non_repo`** to allow directories that are not valid repos on `main:HEAD` (still skipped with a warning when strict).
- **Testing / local override**: **`SHELLENV_COMPOSE_ALLOW_DIRTY`** (`1`, `true`, `yes`, `on`) allows a dirty working tree while still requiring `main`/`master`.
- **Fixture repos**: sample trees under `repos/compose/teamA/env` and `repos/compose/teamB/env` are used in tests for multi-shell compose layouts.

Roadmap items from the original spec (not necessarily implemented yet): remote URL checks (`*.sarc.samsung.com`), symlink vs copy policy, and warnings when the parent rc file lacks a loop to source `~/.{rc}-{tag}` files.

## Features

1. **Preferred shell** — If the operator’s preferred shell differs from `loginShell` (via `getpwent`), guide them to change it. Preference can come from: CLI shell/family name, `SHELL`, or running the tool from a non-login shell.

2. **Discover startup files** — Find startup files in the home directory that are sourced for bash, tcsh, and zsh in all combinations of login vs non-login and interactive vs non-interactive. Do not assume files exist; only report what the shell actually sources (including indirect sources).
   - Bash does not print filenames with `-x`; ship or document a patched bash for filename tracing.
   - Tcsh does not allow `-l` with other options and does not print filenames with `-x`; ship or document a patched tcsh.
   - Zsh already supports useful tracing; keep links/instructions to rebuild patched shells where needed.
   - When listing, show which modes source which files.

3. **Configuration** — Global and user TOML config (see above); CLI and TUI to edit user-level settings.

4. **Invocation modes** — Non-interactive (full task, no prompts), interactive (partial/no commands), TUI (same CLI parameters, curses UI).

5. **Default listing** — Show startup files for the current shell, then the intended shell, then other families. In TUI, expose actions for other commands.

6. **Backup and archive** — Select files to include; configurable backup location; archive removes originals after backup; prune old backups (configurable retention).

7. **Restore** — List backups; select in interactive/TUI; restore safely. If restore would overwrite differing files, prompt to archive the current files first; skip the prompt when there is nothing to conflict.

8. **TUI backup detail** — When a backup is selected in TUI, show files that would be restored/overwritten in the same file-browser style as the discovery view.

9. **Init repo** — URL in config clones/updates a project with initial startup files; error if the path is not that clone; warn if wrong branch or not up to date and offer to fix.

10. **`init` command** — Archive files that would be overwritten if not already archived, then copy family-appropriate files from the repo into the home directory.

11. **`compose`** — Pick optional init files from `compose.paths` (file picker in interactive/TUI; CLI match in non-interactive). First line is a short description comment; longer comments follow. Show the short line next to the filename in lists.
    1. Directories in the path should be `main:HEAD` in a repo with a `*.sarc.samsung.com` URL, or ignored with a warning (policy evolution tracked in code/tests).
    2. Filenames `{shell}{part}-{tag}` with `{shell}{part}` matching a known startup basename; `-{tag}` is unique. Installed as `~/.{name}` (leading dot).
    3. Registry of user selections (persisted with compose state).
    4. Keep composed files up to date (link, copy, or clone — guideline TBD).
    5. Warn if the parent rc (e.g. `~/.zprofile`) does not source the `-*` fragments (repos should include the stanza), e.g.:
    ```sh
    for _rc in $HOME/.zshenv-*; do
        source $_rc
    done
    ```

12. **`update` command** — Compare everything from `init` or `compose` to its source and refresh when out of date.

## Testing and quality

- Each feature should have tests before it is wired into operator scripts and the TUI.
- **Pytest / hermetic config**: point **`SHELLENV_GLOBAL_CONFIG_PATH`** at a temp site TOML; patch or redirect **`user_config_path`** in tests that must not read the developer’s real `~/.shellenv.toml`.
- **Compose**: use **`compose.allow_non_repo`** or `allow_non_repo=True` in API tests for paths that are not git repos; use **`SHELLENV_COMPOSE_ALLOW_DIRTY`** when a real repo on `main` is intentionally dirty; use **`repos/compose/teamA`** / **`teamB`** for integration-style listing tests.

## Issue tracker

The project rule set expects a self-hosted issue tracker with a kanban board (see `.cursor/rules/issue-tracker-kanban.mdc`). When that service is chosen and stable, record URL, credentials location, and quick start here.
