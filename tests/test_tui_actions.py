"""Unit tests for TUI helper functions: backup, disable, and resolve."""

from pathlib import Path

from shellenv.tui import backup_file, disable_file, resolve_path


def test_backup_file_creates_timestamped_copy(tmp_path, monkeypatch):
    """Verify `backup_file` creates a timestamped backup copy in backup dir."""
    src = tmp_path / "startup_test"
    src.write_text("hello world")

    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(backup_dir))

    ok = backup_file(str(src))
    assert ok is True

    files = list(backup_dir.glob("*_startup_test"))
    assert len(files) == 1
    assert files[0].read_text() == "hello world"


def test_disable_file_renames_and_backups(tmp_path, monkeypatch):
    """Verify `disable_file` renames the file and creates a backup."""
    src = tmp_path / "myrc"
    src.write_text("config=1")

    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(backup_dir))

    ok = disable_file(str(src))
    assert ok is True

    # original should no longer exist
    assert not src.exists()

    # renamed file should exist with .disabled suffix
    dest = Path(str(src) + ".disabled")
    assert dest.exists()
    assert dest.read_text() == "config=1"

    # backup should exist
    backups = list(backup_dir.glob("*_myrc"))
    assert len(backups) == 1
    assert backups[0].read_text() == "config=1"


def test_resolve_path_absolute_and_relative(tmp_path, monkeypatch):
    """Resolve absolute paths unchanged and expand user-relative paths."""
    # absolute path returned unchanged
    p = tmp_path / "foo"
    assert resolve_path(str(p)) == str(p)

    # relative path resolved relative to HOME
    monkeypatch.setenv("HOME", str(tmp_path))
    rel = "~/.myrc"
    resolved = resolve_path(rel)
    # normalize with expansion
    assert resolved.endswith("/.myrc")
    assert resolved.startswith(str(tmp_path))
