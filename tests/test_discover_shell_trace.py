"""Tests for discovery using the shell-level tracer and mock fixtures.

These tests rely on the repository fixtures directory and the
`SHELLENV_MOCK_TRACE_DIR` mechanism to exercise the shell-level tracer
without invoking real shells.
"""

import os

from shellenv.discover import discover_startup_files_modes


def test_discover_uses_shell_trace_mock(monkeypatch):
    """Force shell-level tracer and ensure mock traces expose files."""
    # point mock fixtures dir and force shell-level tracer
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("SHELLENV_MOCK_TRACE_DIR", fixtures)
    monkeypatch.setenv("SHELLENV_USE_SHELL_TRACE", "1")

    modes = discover_startup_files_modes(
        "bash",
        shell_path="/bin/bash",
        use_cache=False,
    )
    # expect that mock traces expose files like .bash_profile or .bashrc
    assert any(any(name in (".bash_profile", ".bashrc") for name in modes[m]) for m in modes)


def test_discover_tcsh_uses_shell_trace_mock(monkeypatch):
    """Force shell-level tracer for tcsh.

    Ensure mock traces expose expected files.
    """
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("SHELLENV_MOCK_TRACE_DIR", fixtures)
    monkeypatch.setenv("SHELLENV_USE_SHELL_TRACE", "1")

    modes = discover_startup_files_modes(
        "tcsh",
        shell_path="/bin/tcsh",
        use_cache=False,
    )
    # expect that mock traces expose .cshrc or .login
    assert any(any(name in (".cshrc", ".login", ".tcshrc") for name in modes[m]) for m in modes)


def test_discover_zsh_includes_zshlib_sources_mock(monkeypatch, tmp_path):
    """Regression: zsh often sources helper files from ~/.zshlib/*."""
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("SHELLENV_MOCK_TRACE_DIR", fixtures)
    monkeypatch.setenv("SHELLENV_CACHE_DIR", str(tmp_path / "cache"))
    # Keep in sync with the fixture paths under /home/testuser/...
    monkeypatch.setenv("HOME", "/home/testuser")

    modes = discover_startup_files_modes(
        "zsh",
        shell_path="/bin/zsh",
        use_cache=False,
        include_inferred=False,
        modes=["login_noninteractive"],
    )
    assert ".zshlib/all" in modes["login_noninteractive"]
