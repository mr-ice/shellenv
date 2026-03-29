"""Tests for compose file selection and installation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import tomli_w

from shellenv.compose import (
    INVALID_COMPOSE_SUMMARY,
    ComposeFile,
    _extract_summary,
    _parse_compose_summary,
    _registry_path,
    _shell_rc_files_for_family,
    compose_parent_rc_warnings,
    get_registry,
    install_compose_files,
    list_compose_files,
    split_compose_by_summary_valid,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_TEAM_A_ENV = REPO_ROOT / "repos/compose/teamA/env"
COMPOSE_TEAM_B_ENV = REPO_ROOT / "repos/compose/teamB/env"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


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
        assert _extract_summary(f) == ""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty"
        f.write_text("")
        assert _extract_summary(f) == ""

    def test_no_description_fallback(self, tmp_path):
        f = tmp_path / "zshrc-qux"
        f.write_text("  \n  \n")
        assert _extract_summary(f) == ""


class TestParseComposeSummary:
    """Tests for valid vs invalid compose header comments."""

    def test_shebang_skipped_then_comment(self, tmp_path):
        f = tmp_path / "frag"
        f.write_text("#!/bin/sh\n# Real summary\ntrue\n")
        assert _parse_compose_summary(f) == ("Real summary", True)

    def test_shebang_only_is_invalid(self, tmp_path):
        f = tmp_path / "frag"
        f.write_text("#!/bin/sh\n")
        assert _parse_compose_summary(f) == ("", False)

    def test_hash_without_space(self, tmp_path):
        f = tmp_path / "frag"
        f.write_text("#compact\n")
        assert _parse_compose_summary(f) == ("compact", True)

    def test_code_first_line_invalid(self, tmp_path):
        f = tmp_path / "frag"
        f.write_text("source ~/.foo\n# not counted\n")
        assert _parse_compose_summary(f) == ("", False)


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
        files = list_compose_files("zsh", paths=[], allow_dirty_or_off_main=True)
        assert files == []

    def test_nonexistent_path_skipped(self):
        files = list_compose_files(
            "zsh",
            paths=["/nonexistent/path/12345"],
            allow_dirty_or_off_main=True,
        )
        assert files == []

    def test_finds_matching_files(self, tmp_path):
        (tmp_path / "zshrc-fzf").write_text("# FZF key bindings\nbindkey")
        (tmp_path / "zshrc-nvm").write_text("## NVM\nsource")
        (tmp_path / "zshenv-path").write_text("# PATH additions")
        (tmp_path / "other.txt").write_text("ignore")
        (tmp_path / "zshrc-invalid-suffix").write_text("x")
        _init_repo(tmp_path)

        files = list_compose_files(
            "zsh",
            paths=[str(tmp_path)],
            shell_rc_files=["zshrc", "zshenv"],
            allow_dirty_or_off_main=True,
        )

        by_name = {cf.name: cf for cf in files}
        assert "fzf" in by_name
        assert "nvm" in by_name
        assert "path" in by_name
        assert by_name["fzf"].dest_basename == ".zshrc-fzf"
        assert by_name["fzf"].summary == "FZF key bindings"
        assert by_name["nvm"].summary == "NVM"
        assert by_name["fzf"].summary_valid
        assert by_name["nvm"].summary_valid

    def test_invalid_summary_sorted_after_valid(self, tmp_path):
        (tmp_path / "zshrc-bad").write_text("source /x\n# ignored\n")
        (tmp_path / "zshrc-good").write_text("# Good one\n")
        _init_repo(tmp_path)
        files = list_compose_files(
            "zsh",
            paths=[str(tmp_path)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=True,
        )
        assert [f.name for f in files] == ["good", "bad"]
        assert files[0].summary_valid is True
        assert files[1].summary_valid is False
        assert files[1].summary == INVALID_COMPOSE_SUMMARY

    def test_split_compose_by_summary_valid(self, tmp_path):
        (tmp_path / "zshrc-a").write_text("# A\n")
        (tmp_path / "zshrc-b").write_text("b\n")
        _init_repo(tmp_path)
        files = list_compose_files(
            "zsh",
            paths=[str(tmp_path)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=True,
        )
        v, inv = split_compose_by_summary_valid(files)
        assert len(v) == 1 and v[0].name == "a"
        assert len(inv) == 1 and inv[0].name == "b"

    def test_deduplicates_same_name_from_different_paths(self, tmp_path):
        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "zshrc-foo").write_text("# First")
        _init_repo(d1)
        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "zshrc-foo").write_text("# Second")
        _init_repo(d2)

        files = list_compose_files(
            "zsh",
            paths=[str(d1), str(d2)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=True,
        )
        # First occurrence wins
        assert len([f for f in files if f.name == "foo"]) == 1

    def test_plain_directory_outside_git_scanned_even_when_strict(self, tmp_path):
        d = tmp_path / "nogit"
        d.mkdir()
        (d / "zshrc-plain").write_text("# ok\n")
        strict = list_compose_files(
            "zsh",
            paths=[str(d)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=False,
        )
        assert len(strict) == 1 and strict[0].name == "plain"
        relaxed = list_compose_files(
            "zsh",
            paths=[str(d)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=True,
        )
        assert len(relaxed) == 1 and relaxed[0].name == "plain"

    def test_directory_inside_git_repo_off_main_strict_skips_relaxed_scans(self, tmp_path):
        repo = tmp_path / "mon"
        repo.mkdir()
        env = repo / "env"
        env.mkdir()
        (env / "zshrc-nested").write_text("# nested\n")
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
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "checkout", "-b", "dev"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        strict = list_compose_files(
            "zsh",
            paths=[str(env.resolve())],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=False,
        )
        assert strict == []
        relaxed = list_compose_files(
            "zsh",
            paths=[str(env.resolve())],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=True,
        )
        assert len(relaxed) == 1 and relaxed[0].name == "nested"

    def test_dirty_local_repo_is_cloned_then_scanned(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "zshrc-x").write_text("# x\n")
        _init_repo(repo)
        (repo / "zshrc-x").write_text("# dirty\n")
        files = list_compose_files(
            "zsh",
            paths=[str(repo)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=False,
        )
        assert len(files) == 1 and files[0].name == "x"

    def test_dirty_repo_allowed_with_allow_dirty_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLENV_COMPOSE_ALLOW_DIRTY", "1")
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "zshrc-x").write_text("# x\n")
        _init_repo(repo)
        (repo / "zshrc-x").write_text("# dirty\n")
        files = list_compose_files(
            "zsh",
            paths=[str(repo)],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=False,
        )
        assert len(files) == 1 and files[0].name == "x"

    def test_git_url_is_cloned_and_scanned(self, tmp_path, monkeypatch):
        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t"],
            cwd=origin,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "t"],
            cwd=origin,
            check=True,
            capture_output=True,
        )
        (origin / "zshrc-giturl").write_text("# from url\n")
        subprocess.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=origin, check=True, capture_output=True)

        user_cfg = tmp_path / ".shellenv.toml"
        user_cfg.write_text(
            tomli_w.dumps({"shellenv": {"tool_repo_path": str(tmp_path / ".shellenv")}}),
            encoding="utf8",
        )
        monkeypatch.setattr("shellenv.config.user_config_path", lambda: user_cfg)

        files = list_compose_files(
            "zsh",
            paths=[origin.resolve().as_uri()],
            shell_rc_files=["zshrc"],
            allow_dirty_or_off_main=False,
        )

        assert len(files) == 1
        assert files[0].name == "giturl"
        assert Path(files[0].source_path).exists()
        assert str(tmp_path / ".shellenv" / "compose-sources") in files[0].source_path


class TestComposeFixtureRepos:
    """Integration checks against repos/compose/* sample trees."""

    @pytest.fixture(autouse=True)
    def _fixture_repos_allow_dirty_git(self, monkeypatch):
        """Sample repos are often dirty in dev trees; still require main/master."""
        monkeypatch.setenv("SHELLENV_COMPOSE_ALLOW_DIRTY", "1")

    def test_team_a_tcsh_files_clean_main(self):
        if not COMPOSE_TEAM_A_ENV.is_dir():
            pytest.skip("repos/compose/teamA/env not present")
        files = list_compose_files(
            "tcsh",
            paths=[str(COMPOSE_TEAM_A_ENV.resolve())],
            shell_rc_files=["tcshrc"],
            allow_dirty_or_off_main=False,
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
            allow_dirty_or_off_main=False,
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
            allow_dirty_or_off_main=True,
        )
        # team A has no bashrc-*; team B has bashrc-bono
        assert [f.name for f in files if f.rc_base == "bashrc"] == ["bono"]

    def test_global_config_paths_via_env_site_toml(self, monkeypatch, tmp_path):
        if not COMPOSE_TEAM_A_ENV.is_dir():
            pytest.skip("repos/compose/teamA/env not present")
        user_cfg = tmp_path / ".shellenv.toml"
        user_cfg.write_text("", encoding="utf8")
        monkeypatch.setattr("shellenv.config.user_config_path", lambda: user_cfg)
        site = tmp_path / "site.toml"
        site.write_text(
            tomli_w.dumps({"compose": {"paths": [str(COMPOSE_TEAM_A_ENV.resolve())]}}),
            encoding="utf8",
        )
        monkeypatch.setenv("SHELLENV_GLOBAL_CONFIG_PATH", str(site))
        files = list_compose_files(
            "tcsh",
            shell_rc_files=["tcshrc"],
            allow_dirty_or_off_main=False,
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
            summary_valid=True,
        )

        home = tmp_path / "home"
        home.mkdir()
        installed = install_compose_files([cf], home_dir=home)

        assert len(installed) == 1
        dest = home / ".zshrc-fzf"
        assert dest.exists()
        assert dest.is_symlink()
        assert dest.read_text() == "# FZF\nbindkey"
        assert str(dest) in installed

    def test_updates_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLENV_CACHE_DIR", str(tmp_path / "cache"))
        src = tmp_path / "compose"
        src.mkdir()
        (src / "zshrc-fzf").write_text("# FZF")
        cf = ComposeFile(
            source_path=str(src / "zshrc-fzf"),
            rc_base="zshrc",
            name="fzf",
            dest_basename=".zshrc-fzf",
            summary="FZF",
            summary_valid=True,
        )

        home = tmp_path / "home"
        home.mkdir()
        install_compose_files([cf], home_dir=home)

        reg = get_registry()
        assert len(reg) == 1
        assert reg[0]["source_path"] == str(src / "zshrc-fzf")
        assert reg[0]["dest_basename"] == ".zshrc-fzf"
        assert reg[0]["install_mode"] == "symlink"


class TestComposeAllowedPathKinds:
    """compose.allowed_path_kinds (repo vs directory)."""

    @staticmethod
    def _patch_merged_config(monkeypatch, tmp_path: Path, paths: list[str], **compose_extras: object) -> None:
        data: dict = {
            "compose": {
                "paths": paths,
                "allow_dirty_or_off_main": "false",
                "shell_rc_files": [],
            },
            "shellenv": {"tool_repo_path": str(tmp_path / ".shellenv")},
        }
        data["compose"].update(compose_extras)
        monkeypatch.setattr("shellenv.config.load_merged_config", lambda: data)

    def test_directory_scan_when_only_directory_allowed(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "zshrc-onlydir").write_text("# only dir\n")
        self._patch_merged_config(
            monkeypatch,
            tmp_path,
            [str(plain)],
            allowed_path_kinds=["directory"],
        )
        w: list[str] = []
        files = list_compose_files("zsh", shell_rc_files=["zshrc"], path_kind_warnings=w)
        assert not w
        assert len(files) == 1 and files[0].name == "onlydir"

    def test_repo_skipped_when_only_directory_allowed(self, tmp_path, monkeypatch):
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
        subprocess.run(["git", "commit", "-m", "i"], cwd=repo, check=True, capture_output=True)
        self._patch_merged_config(
            monkeypatch,
            tmp_path,
            [str(repo.resolve())],
            allowed_path_kinds=["directory"],
        )
        w: list[str] = []
        files = list_compose_files("zsh", shell_rc_files=["zshrc"], path_kind_warnings=w)
        assert files == []
        assert w and ("REPO" in w[0] or "repo" in w[0].lower())

    def test_plain_directory_skipped_when_only_repo_allowed(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "zshrc-a").write_text("# A\n")
        self._patch_merged_config(
            monkeypatch,
            tmp_path,
            [str(plain)],
            allowed_path_kinds=["repo"],
        )
        w: list[str] = []
        files = list_compose_files("zsh", shell_rc_files=["zshrc"], path_kind_warnings=w)
        assert files == []
        assert w and "DIRECTORY" in w[0]

    def test_unknown_kind_token_warns(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "zshrc-a").write_text("# A\n")
        self._patch_merged_config(
            monkeypatch,
            tmp_path,
            [str(plain)],
            allowed_path_kinds=["directory", "bogus"],
        )
        w: list[str] = []
        list_compose_files("zsh", shell_rc_files=["zshrc"], path_kind_warnings=w)
        assert any("unknown allowed_path_kinds" in x for x in w)


class TestComposeParentRcWarnings:
    """Post-install checks for parent rc sourcing ~/.{rc}-* fragments."""

    def _cf(self, rc_base: str, name: str) -> ComposeFile:
        return ComposeFile(
            source_path="/tmp/unused",
            rc_base=rc_base,
            name=name,
            dest_basename=f".{rc_base}-{name}",
            summary="x",
            summary_valid=True,
        )

    def test_no_warning_when_parent_sources_glob(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".zshrc").write_text(
            'for _rc in $HOME/.zshrc-*; do [ -f "$_rc" ] && . "$_rc"; done\n'
        )
        cf = self._cf("zshrc", "fzf")
        assert compose_parent_rc_warnings([cf], home_dir=home, family="zsh") == []

    def test_warning_when_parent_missing(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        cf = self._cf("zprofile", "x")
        msgs = compose_parent_rc_warnings([cf], home_dir=home, family="zsh")
        assert len(msgs) == 1
        assert "does not exist" in msgs[0]
        assert ".zprofile" in msgs[0]
        assert "for _rc in $HOME/.zprofile-*" in msgs[0]

    def test_warning_when_parent_has_no_loop(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".bashrc").write_text("# nothing\nexport PATH=/usr/bin\n")
        cf = self._cf("bashrc", "extra")
        msgs = compose_parent_rc_warnings([cf], home_dir=home, family="bash")
        assert len(msgs) == 1
        assert "does not appear to source" in msgs[0]

    def test_tcsh_foreach_detected(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".tcshrc").write_text(
            "foreach _rc ($HOME/.tcshrc-*)\n    source $_rc\nend\n"
        )
        cf = self._cf("tcshrc", "team")
        assert compose_parent_rc_warnings([cf], home_dir=home, family="tcsh") == []

    def test_one_warning_per_rc_base(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".zshrc").write_text("")
        msgs = compose_parent_rc_warnings(
            [self._cf("zshrc", "a"), self._cf("zshrc", "b")],
            home_dir=home,
            family="zsh",
        )
        assert len(msgs) == 1


class TestRegistry:
    """Tests for the compose registry."""

    def test_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLENV_CACHE_DIR", str(tmp_path))
        assert get_registry() == []

    def test_registry_path_respects_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHELLENV_CACHE_DIR", str(tmp_path))
        p = _registry_path()
        assert str(tmp_path) in str(p)
        assert p.name == "compose_registry.json"
