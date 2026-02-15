"""Tests for the discover functionality."""
from env_config.discover import discover_startup_files


def test_discover_returns_candidates_for_bash(tmp_path, monkeypatch):
    """Test that discover_startup_files returns expected candidates for bash family."""
    # Ensure cache directory is set to tmp to avoid touching real home cache
    monkeypatch.setenv("HOME", str(tmp_path))
    files = discover_startup_files("bash", shell_path=None, use_cache=False)
    assert ".bashrc" in files or ".profile" in files


def test_discover_returns_candidates_for_zsh(tmp_path, monkeypatch):
    """Test that discover_startup_files returns expected candidates for zsh family."""
    monkeypatch.setenv("HOME", str(tmp_path))
    files = discover_startup_files("zsh", shell_path=None, use_cache=False)
    assert any(f.startswith(".zsh") for f in files)
