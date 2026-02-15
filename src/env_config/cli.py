"""Command-line interface for env-config (scaffold)."""
from __future__ import annotations

import argparse
import os
import sys

from .detect_shell import detect_current_and_intended_shell


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    p = argparse.ArgumentParser(prog="env-config")
    sub = p.add_subparsers(dest="cmd")

    detect_p = sub.add_parser("detect", help="Detect current and intended shell")
    detect_p.add_argument("--shell", dest="shell", help="Override intended shell (path or name)")
    sub.add_parser("tui", help="Launch TUI (not implemented)")
    disc = sub.add_parser("discover", help="Discover startup files for a shell family")
    disc.add_argument("--family", help="Shell family (bash, zsh, tcsh)")
    disc.add_argument("--shell-path", help="Path to shell executable to use for tracing")
    disc.add_argument(
        "--use-shell-trace",
        action="store_true",
        help="Force shell-level tracing (honors ENVCONFIG_MOCK_TRACE_DIR)",
    )
    disc.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Refresh discovery cache (ignore and remove cached results)",
    )
    disc.add_argument(
        "--existing-only",
        action="store_true",
        help="Only show startup files that currently exist on disk",
    )
    disc.add_argument(
        "--full-paths",
        action="store_true",
        help="Show full absolute paths instead of basenames",
    )
    disc.add_argument(
        "--modes",
        action="store_true",
        help="Show per-invocation-mode discovery (login/interactive combos)",
    )
    disc.add_argument("--tui", action="store_true", help="Show discovery in the TUI")
    trace_p = sub.add_parser(
        "trace", help="Run a shell startup trace and summarize per-file timings"
    )
    trace_p.add_argument("--family", help="Shell family (bash, zsh, tcsh)")
    trace_p.add_argument("--shell-path", help="Path to shell executable to use for tracing")
    trace_p.add_argument(
        "--mode",
        help=(
            "Invocation mode: login_interactive, login_noninteractive, nonlogin_interactive, "
            "nonlogin_noninteractive"
        ),
    )
    trace_p.add_argument(
        "--dry-run", action="store_true", help="Print the tracer command and do not execute it"
    )
    trace_p.add_argument("--output-file", help="Write raw trace output to this file for inspection")
    trace_p.add_argument(
        "--threshold-secs", type=float, help="Flag files taking longer than this many seconds"
    )
    trace_p.add_argument(
        "--threshold-percent",
        type=float,
        help="Flag files taking longer than this percent of total startup time",
    )
    trace_p.add_argument("--tui", action="store_true", help="Show results in a simple TUI")
    trace_p.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostic info about detection and command selection",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    """Command-Line processor for env-config."""
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "detect":
        d = detect_current_and_intended_shell(cli_arg=getattr(args, "shell", None))
        for k, v in d.items():
            print(f"{k}: {v}")
        return 0

    if args.cmd == "tui":
        print("TUI mode not yet implemented")
        return 0

    if args.cmd == "discover":
        from .discover import discover_startup_files, discover_startup_files_modes

        family = getattr(args, "family", None)
        shell_path = getattr(args, "shell_path", None)
        if not family:
            # detect intended shell and use its family when --family omitted
            # pass the provided shell_path as CLI override so detection
            # logic is identical to the `detect` command.
            info = detect_current_and_intended_shell(cli_arg=shell_path)
            family = info.get("intended_family")
            # prefer detected shell path if shell_path not supplied
            if shell_path is None:
                shell_path = info.get("intended_shell")
        # honor CLI flag to force shell-level tracer
        if getattr(args, "use_shell_trace", False):
            os.environ["ENVCONFIG_USE_SHELL_TRACE"] = "1"
        refresh_cache = getattr(args, "refresh_cache", False)
        # normalize family
        if isinstance(family, str):
            family = family.lower()
        if not family:
            family = "bash"
        if getattr(args, "modes", False):
            if refresh_cache:
                from .discover import clear_cache

                clear_cache(family)
            modes = discover_startup_files_modes(
                family,
                shell_path=shell_path,
                existing_only=getattr(args, "existing_only", False),
                full_paths=getattr(args, "full_paths", False),
            )
            if getattr(args, "tui", False):
                try:
                    from .tui import display_discovery_tui

                    display_discovery_tui(modes)
                    return 0
                except Exception as e:
                    print("TUI failed:", e)

            for mode, files in modes.items():
                print(f"== {mode} ==")
                for f in files:
                    print(f)
        else:
            if refresh_cache:
                from .discover import clear_cache

                clear_cache(family)
            files = discover_startup_files(
                family,
                shell_path=shell_path,
                existing_only=getattr(args, "existing_only", False),
                full_paths=getattr(args, "full_paths", False),
            )
            for f in files:
                print(f)
        return 0

    if args.cmd == "trace":
        from .trace import parse_trace, run_shell_trace

        family = getattr(args, "family", None)
        shell_path = getattr(args, "shell_path", None)
        if not family:
            info = detect_current_and_intended_shell(cli_arg=shell_path)
            family = info.get("intended_family")
            if shell_path is None:
                shell_path = info.get("intended_shell")
        # normalize family
        if isinstance(family, str):
            family = family.lower()
        if not family:
            family = "bash"
        mode = getattr(args, "mode", None) or "login_noninteractive"
        # map mode string to args
        mode_map = {
            "login_interactive": ["-l", "-i", "-c", "true"],
            "login_noninteractive": ["-l", "-c", "true"],
            "nonlogin_interactive": ["-i", "-c", "true"],
            "nonlogin_noninteractive": ["-c", "true"],
        }
        args_list = mode_map.get(mode, ["-l", "-c", "true"])
        dry = getattr(args, "dry_run", False)
        out_file = getattr(args, "output_file", None)
        # load merged config defaults when thresholds not specified on CLI
        from .config import load_merged_config

        cfg = load_merged_config()
        thresh_secs = getattr(args, "threshold_secs", None)
        thresh_pct = getattr(args, "threshold_percent", None)
        if thresh_secs is None:
            thresh_secs = cfg.get("trace", {}).get("threshold_secs")
        if thresh_pct is None:
            thresh_pct = cfg.get("trace", {}).get("threshold_percent")

        # Verbose: show detection info and chosen shell/family
        if getattr(args, "verbose", False):
            info = detect_current_and_intended_shell(cli_arg=shell_path)
            print("DETECT:")
            for k, v in info.items():
                print(f"{k}: {v}")
            chosen_shell = shell_path or (
                "bash" if family == "bash" else ("zsh" if family == "zsh" else "tcsh")
            )
            print(f"CHOICE: family={family} shell={chosen_shell}")

        raw = run_shell_trace(
            family, shell_path=shell_path, args=args_list, dry_run=dry, output_file=out_file
        )
        # If dry-run returned a string starting with DRYRUN, print and exit
        if isinstance(raw, str) and raw.startswith("DRYRUN:"):
            print(raw)
            return 0

        parsed = parse_trace(raw, family=family)
        from .trace import analyze_traces

        analysis = analyze_traces(parsed, threshold_secs=thresh_secs, threshold_percent=thresh_pct)

        if getattr(args, "tui", False):
            try:
                from .tui import display_trace_tui

                display_trace_tui(analysis)
                return 0
            except Exception as e:
                print("TUI failed:", e)

        # Print summary
        total = analysis["total"]
        print(f"Total startup duration: {total:.6f}s")
        for item in analysis["items"]:
            flag = "!" if item["flagged"] else " "
            reasons = ",".join(item["reasons"]) if item["reasons"] else ""
            print(
                f"{flag} {item['file']} duration={item['duration']:.6f}s "
                f"cmds={item['commands']} {item['percent']:.1f}% {reasons}"
            )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
