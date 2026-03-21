"""Tests for compose file selection and installation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import tomli_w

from shellctl.compose import (
    ComposeFile,
    _extract_summary,
    _registry_path,
    _shell_rc_files_for_family,
    get_registry,
    install_compose_files,
    list_compose_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_TEAM_A_ENV = REPO_ROOT / "repos/compose/teamA/env"
COMPOSE_TEAM_B_ENV = REPO_ROOT / "repos/compose/teamB/env"


class TestExtractSummary:
    """Tests for summary extraction from shell init files."""

    def test_comment_hash(self, tmp_path):
        f = tmp_path / "zshrc-foo"
        f.write_text("# Load fzf key bindings\nbindkey ...")
        assert _extract_summary(f) == "Load fzf key bindings"

    def test_comment_double_hash(self, tmp_path):
        f = tmp_path / "zshrc-bar"
        f.write_text("## NVM initialization\nsource ...")
        assert _extract_summary(f) == "NVM initialization"

    def test_first_non_comment_line(self, tmp_path):
        f = tmp_path / "zshrc-baz"
        f.write_text("\n\nsource /opt/thing/init.sh\n")
        assert _extract_summary(f) == "source /opt/thing/init.sh"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty"
        f.write_text("")
        assert _extract_summary(f) == ""

    def test_no_description_fallback(self, tmp_path):
        f = tmp_path / "zshrc-qux"
        f.write_text("  \n  \n")
        assert _extract_summary(f) == ""


class TestShellRcFilesForFamily:
    """Tests for shell RC file resolution."""

    def test_uses_config_when_non_empty(self):
        assert _shell_rc_files_for_family("zsh", ["zshrc", "zshenv"]) == [
            "zshrc",
            "zshenv",
        ]

    def test_uses_default_for_zsh(self):
        assert _shell_rc_files_for_family("zsh", []) == [
            "zshrc",
            "zshenv",
            "zprofile",
            "zlogin",
            "zlogout",
        ]

    def test_uses_default_for_bash(self):
        assert _shell_rc_files_for_family("bash", []) == [
            "bashrc",
            "bash_profile",
            "bash_login",
            "profile",
            "bash_logout",
        ]

    def test_uses_default_for_tcsh(self):
        assert _shell_rc_files_for_family("tcsh", []) == [
            "tcshrc",
            "cshrc",
            "login",
        ]


class TestListComposeFiles:
    """Tests for listing compose files."""

    def test_empty_paths(self):
        files = list_compose_files("zsh", paths=[], allow_non_repo=True)
        assert files == []

    def test_nonexistent_path_skipped(self):
        files = list_compose_files(
            "zsh",
            paths=["/nonexistent/path/12345"],
            allow_non_repo=True,
        )
        assert files == []

    def test_finds_matching_files(self, tmp_path):
        (tmp_path / "zshrc-fzf").write_text("# FZF key bindings\nbindkey")
        (tmp_path / "zshrc-nvm").write_text("## NVM\nsource")
        (tmp_path / "zshenv-path").write_text("# PATH additions")
        (tmp_path / "other.txt").write_text("ignore")
        (tmp_path / "zshrc-invalid-suffix").write_text("x")

        files = list_compose_files(
            "zsh",
            paths=[str(tmp_path)],
            shell_rc_files=["zshrc", "zshenv"],
            allow_non_repo=True,
        )

        by_name = {cf.name: cf for cf in files}
        assert "fzf" in by_name
        assert "nvm" in by_name
        assert "path" in by_name
        assert by_name["fzf"].dest_basename == ".zshrc-fzf"
        assert by_name["fzf"].summary == "FZF key bindings"
        assert by_name["nvm"].summary == "NVM"

    def test_deduplicates_same_name_from_different_paths(self, tmp_path):
        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "zshrc-foo").write_text("# First")
        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "zshrc-foo").write_text("# Second")

        files = list_compose_files(
            "zsh",
            paths=[str(d1), str(d2)],
            shell_rc_files=["zshrc"],
            allow_non_repo=True,
        )
        # First occurrence wins
        assert len([f for f in files if f.name == "foo"]) == 1

    def test_non_git_directory_skipped_when_strict(self, tmp_path):
        d = tmp_path / "nogit"
        d.mkdir()
        (d / "zshrc-plain").write_text("# ok\n")
        assert (
            list_compose_files(
                "zsh",
                paths=[str(d)],
                shell_rc_files=["zshrc"],
                allow_non_repo=False,
            )
            == []
        )
        found = list_compose_files(
            "zsh",
            paths=[str(d)],
            shell_rc_files=["zshrc"],
            allow_non_repo=True,
        )
        assert len(found) == 1 and found[0].name == "plain"

    def test_dirty_repo_skipped_without_allow_dirty(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "zshrc-x").write_text("# x\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "m"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "zshrc-x").write_text("# dirty\n")
        files = list_compose_files(
            "zsh",
            paths=[str(repo)],
            shell_rc_files=["zshrc"],
            allow_non_repo=False,
        )
        assert files == []

    def test_dirty_repo_allowed_with_allow_dirty_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLCTL_COMPOSE_ALLOW_DIRTY", "1")
        repo = tmp_path / "r"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "zshrc-x").write_text("# x\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "m"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "zshrc-x").write_text("# dirty\n")
        files = list_compose_files(
            "zsh",
            paths=[str(repo)],
            shell_rc_files=["zshrc"],
            allow_non_repo=False,
        )
        assert len(files) == 1 and files[0].name == "x"


class TestComposeFixtureRepos:
    """Integration checks against repos/compose/* sample trees."""

    def test_team_a_tcsh_files_clean_main(self):
        if not COMPOSE_TEAM_A_ENV.is_dir():
            pytest.skip("repos/compose/teamA/env not present")
        files = list_compose_files(
            "tcsh",
            paths=[str(COMPOSE_TEAM_A_ENV.resolve())],
            shell_rc_files=["tcshrc"],
            allow_non_repo=False,
        )
        names = {f.name for f in files}
        assert names >= {"teamshell", "teammore"}

    def test_team_b_bash_files_clean_main(self):
        if not COMPOSE_TEAM_B_ENV.is_dir():
            pytest.skip("repos/compose/teamB/env not present")
        files = list_compose_files(
            "bash",
            paths=[str(COMPOSE_TEAM_B_ENV.resolve())],
            shell_rc_files=["bashrc", "bash_profile"],
            allow_non_repo=False,
        )
        names = {f.name for f in files}
        assert names >= {"bono"}

    def test_both_paths_together_dedupes_by_rc_and_tag(self):
        if not COMPOSE_TEAM_A_ENV.is_dir() or not COMPOSE_TEAM_B_ENV.is_dir():
            pytest.skip("repos/compose fixtures not present")
        files = list_compose_files(
            "bash",
            paths=[
                str(COMPOSE_TEAM_A_ENV.resolve()),
                str(COMPOSE_TEAM_B_ENV.resolve()),
            ],
            shell_rc_files=["bashrc"],
            allow_non_repo=True,
        )
        # team A has no bashrc-*; team B has bashrc-bono
        assert [f.name for f in files if f.rc_base == "bashrc"] == ["bono"]

    def test_global_config_paths_via_env_site_toml(self, monkeypatch, tmp_path):
        if not COMPOSE_TEAM_A_ENV.is_dir():
            pytest.skip("repos/compose/teamA/env not present")
        user_cfg = tmp_path / ".shellctl.toml"
        user_cfg.write_text("", encoding="utf8")
        monkeypatch.setattr("shellctl.config.user_config_path", lambda: user_cfg)
        site = tmp_path / "site.toml"
        site.write_text(
            tomli_w.dumps({"compose": {"paths": [str(COMPOSE_TEAM_A_ENV.resolve())]}}),
            encoding="utf8",
        )
        monkeypatch.setenv("SHELLCTL_GLOBAL_CONFIG_PATH", str(site))
        files = list_compose_files(
            "tcsh",
            shell_rc_files=["tcshrc"],
            allow_non_repo=False,
        )
        names = {f.name for f in files}
        assert names >= {"teamshell", "teammore"}


class TestInstallComposeFiles:
    """Tests for installing compose files to home."""

    def test_installs_to_home(self, tmp_path):
        src = tmp_path / "compose"
        src.mkdir()
        (src / "zshrc-fzf").write_text("# FZF\nbindkey")
        cf = ComposeFile(
            source_path=str(src / "zshrc-fzf"),
            rc_base="zshrc",
            name="fzf",
            dest_basename=".zshrc-fzf",
            summary="FZF",
        )

        home = tmp_path / "home"
        home.mkdir()
        installed = install_compose_files([cf], home_dir=home)

        assert len(installed) == 1
        dest = home / ".zshrc-fzf"
        assert dest.exists()
        assert dest.read_text() == "# FZF\nbindkey"
        assert str(dest) in installed

    def test_updates_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLCTL_CACHE_DIR", str(tmp_path / "cache"))
        src = tmp_path / "compose"
        src.mkdir()
        (src / "zshrc-fzf").write_text("# FZF")
        cf = ComposeFile(
            source_path=str(src / "zshrc-fzf"),
            rc_base="zshrc",
            name="fzf",
            dest_basename=".zshrc-fzf",
            summary="FZF",
        )

        home = tmp_path / "home"
        home.mkdir()
        install_compose_files([cf], home_dir=home)

        reg = get_registry()
        assert len(reg) == 1
        assert reg[0]["source_path"] == str(src / "zshrc-fzf")
        assert reg[0]["dest_basename"] == ".zshrc-fzf"


class TestRegistry:
    """Tests for the compose registry."""

    def test_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLCTL_CACHE_DIR", str(tmp_path))
        assert get_registry() == []

    def test_registry_path_respects_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLCTL_CACHE_DIR", str(tmp_path))
        p = _registry_path()
        assert str(tmp_path) in str(p)
        assert p.name == "compose_registry.json"
