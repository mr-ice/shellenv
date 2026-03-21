"""Tests for the detect shell functionality."""

import pwd
import shutil
import subprocess
from types import SimpleNamespace

from shellctl.detect_shell import detect_current_and_intended_shell


def test_detect_prefers_cli_arg(monkeypatch):
    """Test that detect_current_and_intended_shell prefers CLI argument over env and parent."""
    monkeypatch.setenv("SHELL", "/bin/bash")
    # parent process mocked but should be ignored in favor of CLI arg
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "zsh -l -i\n")
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_shell="/bin/console-shell"))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/fish" if name == "fish" else None)

    res = detect_current_and_intended_shell(cli_arg="/bin/fish")
    assert res["intended_shell"] == "/bin/fish"
    assert res["intended_family"] == "fish"
    assert res["resolved_source"] == "cli"


def test_detect_uses_shell_env_when_no_arg(monkeypatch):
    """Test that detect_current_and_intended_shell uses SHELL env when CLI arg is not provided."""
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "zsh -l -i\n")
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_shell="/bin/bash"))
    # set SHELL to a path-like value
    monkeypatch.setenv("SHELL", "/bin/bash")

    res = detect_current_and_intended_shell(cli_arg=None)
    assert res["intended_shell"] is not None
    assert res["intended_family"] == "bash"
    assert res["resolved_source"] == "env"


def test_detect_uses_parent_when_no_env(monkeypatch):
    """Test that detect_current_and_intended_shell uses parent process when SHELL env is not set."""
    monkeypatch.delenv("SHELL", raising=False)

    # mock parent to look like zsh
    def fake_check_output(cmd, text=True):
        if "-o" in cmd:
            # return comm or args depending on ps invocation
            if "comm=" in cmd:
                return "zsh\n"
            return "zsh -l -i\n"
        return ""

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_shell="/bin/bash"))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zsh" if name == "zsh" else None)

    res = detect_current_and_intended_shell()
    assert res["intended_family"] == "zsh"
    assert res["resolved_source"] == "parent"


def test_detect_uses_login_shell(monkeypatch):
    """Test that detect_current_and_intended_shell uses loginshell SHELL env is not set.

    To fall all the way through we have to set the return of subprocess.check_output to
    anything not matching a known shell.
    """
    monkeypatch.delenv("SHELL", raising=False)

    monkeypatch.setattr(subprocess, "check_output", "not-a-shell\n")
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_shell="/bin/bash"))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zsh" if name == "zsh" else None)

    res = detect_current_and_intended_shell()
    assert res["intended_family"] == "bash"
    assert res["resolved_source"] == "login"


def test_detect_shell_skips_invalid_args(monkeypatch):
    """Test that detect_current_and_intended_shell returns None on invalid arguments."""
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_shell="/bin/bash"))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zsh" if name == "zsh" else None)

    res = detect_current_and_intended_shell("not-a-shell")
    #
    assert res["intended_family"] == "bash"
    assert res["resolved_source"] == "cli"  # this falls through from the original test
