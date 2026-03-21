"""Tests for the discover modes functionality."""

from shellctl.discover import discover_startup_files_modes


def test_discover_modes_keys_and_contents(tmp_path, monkeypatch):
    """Test that discover_startup_files_modes returns expected mapping to lists of candidates."""
    # isolate cache by pointing HOME to temp dir
    monkeypatch.setenv("HOME", str(tmp_path))
    modes = discover_startup_files_modes("bash", shell_path=None, use_cache=False)
    expected_modes = [
        "login_interactive",
        "login_noninteractive",
        "nonlogin_interactive",
        "nonlogin_noninteractive",
    ]
    for m in expected_modes:
        assert m in modes
        assert isinstance(modes[m], list)

    # at least one mode should include a bash-like file
    assert any(
        any(name in (".bashrc", ".profile", ".bash_profile") for name in modes[m]) for m in modes
    )
