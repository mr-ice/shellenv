"""Tests for discovery trace path normalization.

These tests simulate parsed shell trace records and assert
`_run_tracer` extracts filenames located under `$HOME`.
"""

import os
from types import SimpleNamespace

from shellenv.discover import _run_tracer


def test_run_tracer_collect_output_parsing(monkeypatch, tmp_path):
    """Simulate parsed trace records and verify home-relative names."""
    # set HOME to tmp_path for isolation
    monkeypatch.setenv("HOME", str(tmp_path))
    home = str(tmp_path)
    monkeypatch.setattr(
        "shellenv.trace.collect_startup_file_traces",
        lambda *a, **k: [
            SimpleNamespace(path=os.path.join(home, ".bashrc")),
            SimpleNamespace(path=os.path.join(home, ".bash_profile")),
            SimpleNamespace(path="/etc/hosts"),
        ],
    )

    found = _run_tracer("bash", "/bin/bash", ["-l", "-c", ":"])
    assert isinstance(found, set)
    assert any(name in (".bashrc", ".bash_profile") for name in found)
