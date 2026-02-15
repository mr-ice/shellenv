"""Tests for existing-only and full-paths options in discovery.

These tests verify `discover_startup_files_modes` honors the
`existing_only` and `full_paths` flags when locating startup files.
"""

from env_config.discover import discover_startup_files_modes


def test_existing_only_and_full_paths(tmp_path, monkeypatch):
    """Ensure existing-only and full-paths return absolute paths for files that exist."""
    # set HOME to tmp_path and create a .bashrc file
    monkeypatch.setenv("HOME", str(tmp_path))
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("# test bashrc")

    modes = discover_startup_files_modes(
        "bash", shell_path=None, use_cache=False, existing_only=True, full_paths=True
    )
    # at least one mode should include the full path to .bashrc
    found = False
    for files in modes.values():
        for f in files:
            if str(bashrc) == f:
                found = True
    assert found
