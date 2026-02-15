"""Tests that the system-tracer (strace) parser extracts home files correctly.

These tests simulate `strace` output and assert `_run_tracer` extracts
filenames located under `$HOME`.
"""

import os
from types import SimpleNamespace

from env_config.discover import _run_tracer


class FakeProc:
    """A tiny namespace-like fake process object used for monkeypatching.

    Attributes
    ----------
    stderr: str
        Simulated standard error text from the tracer.
    stdout: str
        Simulated standard output text (unused by these tests).
    """

    def __init__(self, stderr, stdout=""):
        self.stderr = stderr
        self.stdout = stdout


def test_strace_output_parsing(monkeypatch, tmp_path):
    """Simulate `strace` output and verify `_run_tracer` returns home-relative names."""
    # set HOME to tmp_path for isolation
    monkeypatch.setenv("HOME", str(tmp_path))
    # simulate strace being present
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/strace" if name == "strace" else None
    )

    # craft a fake strace stderr containing open/openat calls
    home = str(tmp_path)
    bashrc = os.path.join(home, ".bashrc")
    profile = os.path.join(home, ".bash_profile")
    stderr = (
        f'openat(AT_FDCWD, "{bashrc}", O_RDONLY) = 3\n'
        f'open("/etc/hosts", O_RDONLY) = 3\n'
        f'open("{profile}", O_RDONLY) = -1 ENOENT (No such file)\n'
    )

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(stderr=stderr, stdout="", returncode=0),
    )

    found = _run_tracer("bash", "/bin/bash", ["-l", "-c", ":"])
    assert isinstance(found, set)
    assert any(name in (".bashrc", ".bash_profile") for name in found)
