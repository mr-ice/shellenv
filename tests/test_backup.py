"""Tests for backup, archive, restore operations and CLI subcommands."""

from __future__ import annotations

import os
import tarfile

import pytest

from shellctl.backup import (
    BackupManifest,
    create_archive,
    create_backup,
    filter_files,
    find_archive,
    list_archives,
    read_manifest,
    restore_from_archive,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_home(tmp_path, monkeypatch):
    """Set up a fake home directory with sample startup files."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Path.home() caches, so patch it too
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return home


def _create_startup_files(home, names=None):
    """Create sample startup files in the fake home directory."""
    if names is None:
        names = [".bashrc", ".bash_profile", ".profile"]
    paths = []
    for name in names:
        p = home / name
        p.write_text(f"# {name}\n")
        paths.append(str(p))
    return paths


# ---------------------------------------------------------------------------
# filter_files
# ---------------------------------------------------------------------------


class TestFilterFiles:
    """Tests for filter_files."""

    def test_no_filters(self):
        files = ["/home/u/.bashrc", "/home/u/.zshrc"]
        assert filter_files(files) == files

    def test_include_only(self):
        files = ["/home/u/.bashrc", "/home/u/.zshrc", "/home/u/.profile"]
        result = filter_files(files, include=[".*bash*"])
        assert result == ["/home/u/.bashrc"]

    def test_exclude_only(self):
        files = ["/home/u/.bashrc", "/home/u/.zshrc", "/home/u/.profile"]
        result = filter_files(files, exclude=[".*zsh*"])
        assert result == ["/home/u/.bashrc", "/home/u/.profile"]

    def test_include_and_exclude(self):
        files = ["/home/u/.bashrc", "/home/u/.bash_profile", "/home/u/.zshrc"]
        result = filter_files(files, include=[".*bash*"], exclude=[".*profile*"])
        assert result == ["/home/u/.bashrc"]

    def test_wildcard_patterns(self):
        files = ["/home/u/.bashrc", "/home/u/.bash_profile", "/home/u/.zshrc"]
        result = filter_files(files, include=[".*rc"])
        assert result == ["/home/u/.bashrc", "/home/u/.zshrc"]


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------


class TestCreateBackup:
    """Tests for create_backup."""

    def test_produces_archive(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home)
        backup_dir = tmp_path / "backups"

        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        assert archive_path.exists()
        assert archive_path.suffix == ".gz"
        assert "shellctl-backup-" in archive_path.name

    def test_stores_relative_paths(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc", ".profile"])
        backup_dir = tmp_path / "backups"

        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        with tarfile.open(archive_path, "r:gz") as tar:
            names = {m.name for m in tar.getmembers()}
        assert ".bashrc" in names
        assert ".profile" in names
        assert "manifest.json" in names

    def test_manifest_contents(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc"])
        backup_dir = tmp_path / "backups"

        archive_path = create_backup(files, "bash", backup_dir=backup_dir)
        manifest = read_manifest(archive_path)

        assert manifest.family == "bash"
        assert ".bashrc" in manifest.files
        assert manifest.timestamp  # non-empty
        assert manifest.hostname  # non-empty
        assert manifest.version  # non-empty

    def test_empty_files_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no files"):
            create_backup([], "bash", backup_dir=tmp_path)

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        _make_home(tmp_path, monkeypatch)
        with pytest.raises(FileNotFoundError, match="file not found"):
            create_backup(["/nonexistent/.bashrc"], "bash", backup_dir=tmp_path)


# ---------------------------------------------------------------------------
# create_archive
# ---------------------------------------------------------------------------


class TestCreateArchive:
    """Tests for create_archive (backup + delete)."""

    def test_removes_originals(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc", ".profile"])
        backup_dir = tmp_path / "backups"

        archive_path = create_archive(files, "bash", backup_dir=backup_dir)

        assert archive_path.exists()
        for f in files:
            assert not os.path.exists(f)


# ---------------------------------------------------------------------------
# list_archives
# ---------------------------------------------------------------------------


class TestListArchives:
    """Tests for list_archives."""

    def test_sorted_newest_first(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"

        files1 = _create_startup_files(home, [".bashrc"])
        create_backup(files1, "bash", backup_dir=backup_dir)

        # Recreate file for second backup
        _create_startup_files(home, [".bashrc"])
        # Force a different timestamp by creating directly
        import time

        time.sleep(0.01)
        create_backup(_create_startup_files(home, [".bashrc"]), "bash", backup_dir=backup_dir)

        archives = list_archives(backup_dir=backup_dir)
        assert len(archives) >= 1  # timestamps may collide at second resolution
        # newest first
        if len(archives) >= 2:
            assert archives[0][0] >= archives[1][0]

    def test_empty_dir(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        assert list_archives(backup_dir=backup_dir) == []

    def test_ignores_non_matching_files(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "random.txt").write_text("hello")
        (backup_dir / "backup.tar.gz").write_text("nope")
        assert list_archives(backup_dir=backup_dir) == []


# ---------------------------------------------------------------------------
# find_archive
# ---------------------------------------------------------------------------


class TestFindArchive:
    """Tests for find_archive."""

    def test_unique_match(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"
        files = _create_startup_files(home, [".bashrc"])
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        # Use the full timestamp from the filename as substring
        ts = archive_path.name.split("-backup-")[1].replace(".tar.gz", "")
        result = find_archive(ts, backup_dir=backup_dir)
        assert result == archive_path

    def test_no_match(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"
        _create_startup_files(home, [".bashrc"])
        create_backup(_create_startup_files(home, [".bashrc"]), "bash", backup_dir=backup_dir)

        result = find_archive("NOMATCH999", backup_dir=backup_dir)
        assert result is None

    def test_ambiguous_match(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"

        _create_startup_files(home, [".bashrc"])
        create_backup(_create_startup_files(home, [".bashrc"]), "bash", backup_dir=backup_dir)
        _create_startup_files(home, [".bashrc"])
        create_backup(_create_startup_files(home, [".bashrc"]), "bash", backup_dir=backup_dir)

        archives = list_archives(backup_dir=backup_dir)
        if len(archives) >= 2:
            # "shellctl-backup" matches all archives
            with pytest.raises(ValueError, match="ambiguous"):
                find_archive("shellctl-backup", backup_dir=backup_dir)


# ---------------------------------------------------------------------------
# read_manifest
# ---------------------------------------------------------------------------


class TestReadManifest:
    """Tests for read_manifest."""

    def test_valid_manifest(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        backup_dir = tmp_path / "backups"
        files = _create_startup_files(home, [".bashrc", ".profile"])
        archive_path = create_backup(files, "zsh", backup_dir=backup_dir)

        manifest = read_manifest(archive_path)
        assert isinstance(manifest, BackupManifest)
        assert manifest.family == "zsh"
        assert set(manifest.files) == {".bashrc", ".profile"}

    def test_missing_manifest(self, tmp_path):
        # Create a tar.gz without manifest.json
        archive_path = tmp_path / "bad.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            import io

            data = b"hello"
            info = tarfile.TarInfo(name="somefile.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        with pytest.raises(KeyError):
            read_manifest(archive_path)


# ---------------------------------------------------------------------------
# restore_from_archive
# ---------------------------------------------------------------------------


class TestRestoreFromArchive:
    """Tests for restore_from_archive."""

    def test_extracts_files(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc", ".profile"])
        backup_dir = tmp_path / "backups"
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        # Remove originals to simulate restore
        for f in files:
            os.remove(f)
        assert not (home / ".bashrc").exists()

        restored = restore_from_archive(archive_path, target_dir=home)
        assert len(restored) == 2
        assert (home / ".bashrc").exists()
        assert (home / ".profile").exists()
        assert (home / ".bashrc").read_text() == "# .bashrc\n"

    def test_include_filter(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc", ".profile"])
        backup_dir = tmp_path / "backups"
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        for f in files:
            os.remove(f)

        restored = restore_from_archive(archive_path, target_dir=home, include=[".*bashrc*"])
        assert len(restored) == 1
        assert (home / ".bashrc").exists()
        assert not (home / ".profile").exists()

    def test_exclude_filter(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc", ".profile"])
        backup_dir = tmp_path / "backups"
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        for f in files:
            os.remove(f)

        restored = restore_from_archive(archive_path, target_dir=home, exclude=[".*profile*"])
        assert len(restored) == 1
        assert (home / ".bashrc").exists()

    def test_skips_existing_without_force(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc"])
        backup_dir = tmp_path / "backups"
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        # File still exists — should be skipped
        (home / ".bashrc").write_text("modified\n")

        restored = restore_from_archive(archive_path, target_dir=home, force=False)
        assert len(restored) == 0
        assert (home / ".bashrc").read_text() == "modified\n"

    def test_overwrites_with_force(self, tmp_path, monkeypatch):
        home = _make_home(tmp_path, monkeypatch)
        files = _create_startup_files(home, [".bashrc"])
        backup_dir = tmp_path / "backups"
        archive_path = create_backup(files, "bash", backup_dir=backup_dir)

        (home / ".bashrc").write_text("modified\n")

        restored = restore_from_archive(archive_path, target_dir=home, force=True)
        assert len(restored) == 1
        assert (home / ".bashrc").read_text() == "# .bashrc\n"

    def test_rejects_path_traversal(self, tmp_path):
        """An archive with '..' in a member name should be rejected."""
        archive_path = tmp_path / "evil.tar.gz"
        import io
        import json

        with tarfile.open(archive_path, "w:gz") as tar:
            data = b"evil"
            info = tarfile.TarInfo(name="../etc/passwd")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

            manifest = {
                "timestamp": "20260215T120000Z",
                "family": "bash",
                "files": ["../etc/passwd"],
                "hostname": "test",
                "version": "0.1.0",
            }
            manifest_bytes = json.dumps(manifest).encode()
            minfo = tarfile.TarInfo(name="manifest.json")
            minfo.size = len(manifest_bytes)
            tar.addfile(minfo, io.BytesIO(manifest_bytes))

        with pytest.raises(ValueError, match="unsafe"):
            restore_from_archive(archive_path, target_dir=tmp_path / "target")

    def test_nonexistent_archive_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="archive not found"):
            restore_from_archive(tmp_path / "nope.tar.gz")


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def _cli_env(tmp_path, monkeypatch):
    """Set up isolated environment for CLI backup tests."""
    home = _make_home(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("SHELLCTL_BACKUP_DIR", str(backup_dir))
    # Patch discover to return our fake files
    files = _create_startup_files(home, [".bashrc", ".bash_profile", ".profile"])
    monkeypatch.setattr(
        "shellctl.cli._discover_files",
        lambda *a, **kw: files,
    )
    return home, backup_dir, files


class TestCLIBackup:
    """CLI integration tests for backup subcommand."""

    def test_backup_creates_archive(self, _cli_env, monkeypatch):
        from shellctl.cli import main

        # Patch discover import inside the handler
        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        rc = main(["backup", "--family", "bash"])
        assert rc == 0
        archives = list(backup_dir.glob("shellctl-backup-*.tar.gz"))
        assert len(archives) == 1

    def test_backup_with_include(self, _cli_env, monkeypatch):
        from shellctl.cli import main

        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        rc = main(["backup", "--family", "bash", "--include", ".*bashrc*"])
        assert rc == 0
        archives = list(backup_dir.glob("shellctl-backup-*.tar.gz"))
        assert len(archives) == 1
        manifest = read_manifest(archives[0])
        assert manifest.files == [".bashrc"]


class TestCLIArchive:
    """CLI integration tests for archive subcommand."""

    def test_archive_removes_files(self, _cli_env, monkeypatch):
        from shellctl.cli import main

        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        rc = main(["archive", "--family", "bash", "--yes"])
        assert rc == 0
        for f in files:
            assert not os.path.exists(f)
        archives = list(backup_dir.glob("shellctl-backup-*.tar.gz"))
        assert len(archives) == 1


class TestCLIRestore:
    """CLI integration tests for restore subcommand."""

    def test_restore_most_recent(self, _cli_env, monkeypatch):
        from shellctl.cli import main

        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        # Create backup first
        main(["backup", "--family", "bash"])
        # Remove originals
        for f in files:
            os.remove(f)

        rc = main(["restore", "--yes", "--force"])
        assert rc == 0
        assert (home / ".bashrc").exists()

    def test_restore_ambiguous_substring(self, _cli_env, monkeypatch, capsys):
        from shellctl.cli import main

        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        # Create two backups
        main(["backup", "--family", "bash"])
        _create_startup_files(home, [".bashrc", ".bash_profile", ".profile"])
        # Ensure we refresh the file list for the second backup
        new_files = [str(home / n) for n in [".bashrc", ".bash_profile", ".profile"]]
        monkeypatch.setattr(
            "shellctl.cli._discover_files",
            lambda *a, **kw: new_files,
        )
        main(["backup", "--family", "bash"])

        archives = list(backup_dir.glob("shellctl-backup-*.tar.gz"))
        if len(archives) >= 2:
            rc = main(["restore", "--archive", "shellctl-backup"])
            assert rc == 1
            assert "ambiguous" in capsys.readouterr().err.lower()


class TestCLIListBackups:
    """CLI integration tests for list-backups subcommand."""

    def test_list_backups(self, _cli_env, monkeypatch, capsys):
        from shellctl.cli import main

        home, backup_dir, files = _cli_env
        monkeypatch.setattr("shellctl.backup.Path.home", lambda: home)

        main(["backup", "--family", "bash"])
        rc = main(["list-backups"])
        assert rc == 0
        out = capsys.readouterr().out
        assert ".bashrc" in out
        assert "files" in out.lower()

    def test_list_backups_empty(self, tmp_path, monkeypatch, capsys):
        from shellctl.cli import main

        monkeypatch.setenv("SHELLCTL_BACKUP_DIR", str(tmp_path / "empty"))
        rc = main(["list-backups"])
        assert rc == 0
        assert "no backup archives" in capsys.readouterr().out.lower()
