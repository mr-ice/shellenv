"""Shared shell invocation mode definitions for discover and trace.

Provides a single source of truth for mode names, short tags, and
the mapping to shell invocation arguments. Used by both discover
and trace commands.
"""

from __future__ import annotations

# Full mode names (login/nonlogin x interactive/noninteractive)
INVOCATION_MODES = (
    "login_interactive",
    "login_noninteractive",
    "nonlogin_interactive",
    "nonlogin_noninteractive",
)

# Short tags for CLI: li, ln, ni, nn
SHORT_TAGS = {
    "li": "login_interactive",
    "ln": "login_noninteractive",
    "ni": "nonlogin_interactive",
    "nn": "nonlogin_noninteractive",
}

# Reverse: full name -> short tag (for help text)
MODE_TO_SHORT = {v: k for k, v in SHORT_TAGS.items()}


def resolve_modes(spec: str | list[str] | None) -> list[str]:
    """Resolve mode spec to list of full mode names.

    Parameters
    ----------
    spec : str or list[str] or None
        - None: all modes
        - "all": all modes
        - Single tag or full name: one mode (e.g. "li", "login_interactive")
        - List of tags/names: those modes

    Returns
    -------
    list[str]
        Full mode names in canonical order.
    """
    if spec is None:
        return list(INVOCATION_MODES)
    if isinstance(spec, list):
        resolved = []
        for s in spec:
            resolved.extend(resolve_modes(s))
        # Dedupe and preserve canonical order
        seen = set()
        out = []
        for m in INVOCATION_MODES:
            if m in resolved and m not in seen:
                out.append(m)
                seen.add(m)
        return out
    s = str(spec).strip().lower()
    if s == "all" or s == "":
        return list(INVOCATION_MODES)
    full = SHORT_TAGS.get(s, s)
    if full in INVOCATION_MODES:
        return [full]
    return []


def mode_to_args(
    family: str,
    mode: str,
    *,
    exit_cmd: str = ":",
) -> list[str]:
    """Return shell invocation args for a given family and mode.

    Parameters
    ----------
    family : str
        Shell family (bash, zsh, tcsh).
    mode : str
        Full mode name (e.g. login_interactive).

    Returns
    -------
    list[str]
        Args to pass to the shell (e.g. ["-l", "-i", "-c", ":"]).
    """
    if mode not in INVOCATION_MODES:
        return ["-l", "-c", ":"]
    login, interactive = mode.split("_")
    args: list[str] = []
    if family.lower() in ("bash", "zsh", "tcsh"):
        if login == "login":
            args.append("-l")
        if interactive == "interactive":
            args.append("-i")
    else:
        if login == "login":
            args.append("-l")
        if interactive == "interactive":
            args.append("-i")
    # Always add -c <exit_cmd> so the shell exits after startup (avoids blocking).
    args.extend(["-c", exit_cmd])
    return args


def mode_choices_for_parser() -> tuple[list[str], str]:
    """Return (choices_list, help_text) for argparse --mode.

    Includes short tags and full names so both work.
    """
    choices = ["all"] + list(SHORT_TAGS) + list(INVOCATION_MODES)
    parts = [f"{k}={v}" for k, v in SHORT_TAGS.items()]
    help_text = f"Mode: {', '.join(parts)}, or 'all'. Short tags: li, ln, ni, nn"
    return choices, help_text
