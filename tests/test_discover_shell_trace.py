"""Tests for discovery using the shell-level tracer and mock fixtures.

These tests rely on the repository fixtures directory and the
`ENVCONFIG_MOCK_TRACE_DIR` mechanism to exercise the shell-level tracer
without invoking real shells.
"""

import os

from env_config.discover import discover_startup_files_modes


def test_discover_uses_shell_trace_mock(monkeypatch):
    """Force use of shell-level tracer and ensure mock traces expose expected files."""
    # point mock fixtures dir and force shell-level tracer
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("ENVCONFIG_MOCK_TRACE_DIR", fixtures)
    monkeypatch.setenv("ENVCONFIG_USE_SHELL_TRACE", "1")

    modes = discover_startup_files_modes("bash", shell_path="/bin/bash", use_cache=False)
    # expect that mock traces expose files like .bash_profile or .bashrc
    assert any(any(name in (".bash_profile", ".bashrc") for name in modes[m]) for m in modes)
