"""Tests for backup/restore TUI components and CLI --tui dispatch."""

import curses

import pytest

from shellenv.tui import (
    ChecklistState,
    _archive_list_for_display,
    _build_backup_items,
    _checklist_nav,
    _prepare_backup,
    _restore_file_status,
)

# ---------------------------------------------------------------------------
# ChecklistState + _checklist_nav
# ---------------------------------------------------------------------------


class TestChecklistNav:
    """Tests for the pure checklist navigation helper."""

    def _state(self, n=3):
        return ChecklistState(
            items=[f"item{i}" for i in range(n)],
            checked=[False] * n,
        )

    def test_move_down(self):
        s = self._state()
        _checklist_nav(ord("j"), s, display_lines=10)
        assert s.selected == 1

    def test_move_down_curses_key(self):
        s = self._state()
        _checklist_nav(curses.KEY_DOWN, s, display_lines=10)
        assert s.selected == 1

    def test_move_up(self):
        s = self._state()
        s.selected = 2
        _checklist_nav(ord("k"), s, display_lines=10)
        assert s.selected == 1

    def test_move_up_at_top(self):
        s = self._state()
        _checklist_nav(ord("k"), s, display_lines=10)
        assert s.selected == 0

    def test_move_down_at_bottom(self):
        s = self._state()
        s.selected = 2
        _checklist_nav(ord("j"), s, display_lines=10)
        assert s.selected == 2

    def test_toggle_space(self):
        s = self._state()
        _checklist_nav(ord(" "), s, display_lines=10)
        assert s.checked == [True, False, False]
        _checklist_nav(ord(" "), s, display_lines=10)
        assert s.checked == [False, False, False]

    def test_select_all(self):
        s = self._state()
        _checklist_nav(ord("a"), s, display_lines=10)
        assert all(s.checked)

    def test_select_none(self):
        s = self._state()
        s.checked = [True, True, True]
        _checklist_nav(ord("n"), s, display_lines=10)
        assert not any(s.checked)

    def test_scrolling_down(self):
        s = self._state(n=20)
        for _ in range(6):
            _checklist_nav(ord("j"), s, display_lines=5)
        assert s.selected == 6
        assert s.top > 0

    def test_scrolling_up(self):
        s = self._state(n=20)
        s.selected = 10
        s.top = 8
        _checklist_nav(ord("k"), s, display_lines=5)
        assert s.selected == 9


# ---------------------------------------------------------------------------
# _prepare_backup
# ---------------------------------------------------------------------------


class TestPrepareBackup:
    """Tests for _prepare_backup."""

    def test_filters_unchecked(self):
        files = ["/home/u/.bashrc", "/home/u/.profile", "/home/u/.zshrc"]
        checked = [True, False, True]
        result = _prepare_backup(files, checked)
        assert result == ["/home/u/.bashrc", "/home/u/.zshrc"]

    def test_all_checked(self):
        files = ["/a", "/b"]
        result = _prepare_backup(files, [True, True])
        assert result == ["/a", "/b"]

    def test_raises_on_none_selected(self):
        with pytest.raises(ValueError, match="no files"):
            _prepare_backup(["/a", "/b"], [False, False])


# ---------------------------------------------------------------------------
# _build_backup_items
# ---------------------------------------------------------------------------


class TestBuildBackupItems:
    """Tests for _build_backup_items."""

    def test_active_family_first_and_checked(self):
        groups = [
            ("bash", ["/home/.bashrc", "/home/.bash_profile"]),
            ("zsh", ["/home/.zshrc"]),
        ]
        labels, checked, seps = _build_backup_items(groups, "bash")
        # First item is a separator for bash
        assert "bash" in labels[0] and "active" in labels[0]
        assert 0 in seps
        # bash files are checked
        assert labels[1] == "/home/.bashrc"
        assert checked[1] is True
        assert labels[2] == "/home/.bash_profile"
        assert checked[2] is True
        # zsh separator + unchecked file
        zsh_sep = seps[1]
        assert "zsh" in labels[zsh_sep]
        assert labels[zsh_sep + 1] == "/home/.zshrc"
        assert checked[zsh_sep + 1] is False

    def test_active_family_not_in_groups(self):
        groups = [("zsh", ["/home/.zshrc"])]
        labels, checked, seps = _build_backup_items(groups, "bash")
        # No active section, just zsh
        assert len(seps) == 1
        assert "zsh" in labels[0]
        assert checked[1] is False

    def test_empty_groups(self):
        labels, checked, seps = _build_backup_items([], "bash")
        assert labels == []
        assert checked == []
        assert seps == []

    def test_separators_are_not_file_paths(self):
        groups = [
            ("bash", ["/home/.bashrc"]),
            ("zsh", ["/home/.zshrc"]),
        ]
        labels, checked, seps = _build_backup_items(groups, "bash")
        sep_set = set(seps)
        for i, label in enumerate(labels):
            if i in sep_set:
                assert label.startswith("──")
                assert checked[i] is False
            else:
                assert label.startswith("/")


# ---------------------------------------------------------------------------
# _restore_file_status
# ---------------------------------------------------------------------------


class TestRestoreFileStatus:
    """Tests for _restore_file_status."""

    def test_detects_existing_files(self, tmp_path):
        (tmp_path / ".bashrc").write_text("x")
        result = _restore_file_status([".bashrc", ".profile"], tmp_path)
        assert result == [(".bashrc", True), (".profile", False)]

    def test_empty_list(self, tmp_path):
        assert _restore_file_status([], tmp_path) == []


# ---------------------------------------------------------------------------
# _archive_list_for_display
# ---------------------------------------------------------------------------


class TestArchiveListForDisplay:
    """Tests for _archive_list_for_display."""

    def test_reads_manifests(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".bashrc").write_text("export PATH=/usr/bin")
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        from shellenv.backup import create_backup, list_archives

        create_backup([str(home / ".bashrc")], "bash", backup_dir=tmp_path)
        archives = list_archives(backup_dir=tmp_path)
        result = _archive_list_for_display(archives)
        assert len(result) == 1
        assert result[0]["family"] == "bash"
        assert result[0]["file_count"] == "1"

    def test_empty_archives(self):
        assert _archive_list_for_display([]) == []


# ---------------------------------------------------------------------------
# CLI --tui dispatch tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def _cli_backup_env(tmp_path, monkeypatch):
    """Set up isolated environment for CLI backup/restore TUI tests."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("# bashrc")
    (home / ".bash_profile").write_text("# profile")
    (home / ".zshrc").write_text("# zshrc")
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(tmp_path / "backups"))

    bash_files = [str(home / ".bashrc"), str(home / ".bash_profile")]
    zsh_files = [str(home / ".zshrc")]

    def _fake_discover(family):
        if family == "bash":
            return list(bash_files)
        if family == "zsh":
            return list(zsh_files)
        return []

    monkeypatch.setattr("shellenv.cli._discover_files", _fake_discover)
    from shellenv.backup import create_backup

    create_backup([str(home / ".bashrc")], "bash", backup_dir=tmp_path / "backups")
    return home, bash_files, zsh_files


class TestCLIBackupTUI:
    """Verify --tui flag dispatches with the same family-scoped file set as CLI mode."""

    def test_backup_tui_receives_selected_family_only(self, _cli_backup_env, monkeypatch):
        from shellenv.cli import main

        home, bash_files, zsh_files = _cli_backup_env
        called = {}

        def fake_tui(groups, active_family, archive_mode=False):
            called["groups"] = groups
            called["active_family"] = active_family
            called["archive_mode"] = archive_mode
            return None

        monkeypatch.setattr("shellenv.tui.display_backup_tui", fake_tui)
        rc = main(["backup", "--family", "bash", "--tui"])
        assert rc == 0
        assert called["active_family"] == "bash"
        assert called["archive_mode"] is False
        assert called["groups"] == [("bash", bash_files)]

    def test_archive_tui_sets_archive_mode(self, _cli_backup_env, monkeypatch):
        called = {}

        def fake_tui(groups, active_family, archive_mode=False):
            called["archive_mode"] = archive_mode
            called["active_family"] = active_family
            return None

        monkeypatch.setattr("shellenv.tui.display_backup_tui", fake_tui)
        from shellenv.cli import main

        rc = main(["archive", "--family", "bash", "--tui"])
        assert rc == 0
        assert called["archive_mode"] is True


class TestCLIRestoreTUI:
    """Verify --tui flag dispatches to display_restore_tui."""

    def test_restore_tui_called_with_cli_filters(self, _cli_backup_env, monkeypatch):
        called = {}

        def fake_tui(
            backup_dir=None,
            *,
            preselected_archive=None,
            include=None,
            exclude=None,
            force_default=False,
        ):
            called["invoked"] = True
            called["preselected_archive"] = preselected_archive
            called["include"] = include
            called["exclude"] = exclude
            called["force_default"] = force_default
            return []

        monkeypatch.setattr("shellenv.tui.display_restore_tui", fake_tui)
        from shellenv.cli import main

        rc = main(["restore", "--tui", "--include", ".bashrc", "--exclude", ".zshrc", "--force"])
        assert rc == 0
        assert called.get("invoked")
        assert called["include"] == [".bashrc"]
        assert called["exclude"] == [".zshrc"]
        assert called["force_default"] is True
        assert called["preselected_archive"] is not None

    def test_restore_tui_reports_count(self, _cli_backup_env, monkeypatch, capsys):
        def fake_tui(
            backup_dir=None,
            *,
            preselected_archive=None,
            include=None,
            exclude=None,
            force_default=False,
        ):
            return ["/home/.bashrc", "/home/.profile"]

        monkeypatch.setattr("shellenv.tui.display_restore_tui", fake_tui)
        from shellenv.cli import main

        rc = main(["restore", "--tui"])
        assert rc == 0
        assert "restored 2 file(s)" in capsys.readouterr().out
