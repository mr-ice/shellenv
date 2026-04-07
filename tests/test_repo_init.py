"""Tests for init-repo and init (startup repo clone + install into home)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shellenv.repo_init import (
    ensure_startup_repo_ready,
    iter_family_init_files,
    load_repo_settings_from_config,
    remote_urls_match,
    run_init_home,
)


def _git_config_identity(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _create_upstream_repo(path: Path, bashrc: str = "upstream\n") -> None:
    path.mkdir(parents=True)
    (path / "bash").mkdir()
    (path / "bash" / ".bashrc").write_text(bashrc, encoding="utf8")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    _git_config_identity(path)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _cfg(url: str, dest: Path, branch: str = "main") -> dict:
    return {
        "repo": {
            "url": url,
            "destination": str(dest),
            "branch": branch,
        }
    }


def test_remote_urls_match_paths(tmp_path: Path) -> None:
    a = tmp_path / "repo"
    a.mkdir()
    p = str(a.resolve())
    assert remote_urls_match(p, p)
    assert remote_urls_match(f"file://{p}", p)


def test_load_repo_settings_errors() -> None:
    with pytest.raises(ValueError, match="repo.url"):
        load_repo_settings_from_config({"repo": {"destination": "/x"}})
    with pytest.raises(ValueError, match="repo.destination"):
        load_repo_settings_from_config({"repo": {"url": "https://example.com/r.git"}})


def test_ensure_startup_repo_ready_clones(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream)
    clone_dest = tmp_path / "clone"
    warnings = ensure_startup_repo_ready(cfg=_cfg(str(upstream.resolve()), clone_dest))
    assert isinstance(warnings, list)
    assert (clone_dest / ".git").is_dir()
    assert (clone_dest / "bash" / ".bashrc").read_text(encoding="utf8") == "upstream\n"


def test_ensure_startup_repo_ready_empty_destination_dir(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream)
    clone_dest = tmp_path / "clone"
    clone_dest.mkdir()
    ensure_startup_repo_ready(cfg=_cfg(str(upstream.resolve()), clone_dest))
    assert (clone_dest / ".git").is_dir()


def test_ensure_startup_repo_ready_rejects_wrong_origin(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream)
    other = tmp_path / "other"
    _create_upstream_repo(other, bashrc="other\n")
    clone_dest = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(other.resolve()), str(clone_dest)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(RuntimeError, match="not a clone"):
        ensure_startup_repo_ready(cfg=_cfg(str(upstream.resolve()), clone_dest))


def test_iter_family_init_files(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream)
    pairs = iter_family_init_files(upstream, "bash")
    assert len(pairs) == 1
    assert pairs[0][0].name == ".bashrc"
    assert pairs[0][1] == ".bashrc"


def test_run_init_home_copies_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream, bashrc="from_repo\n")
    clone_dest = tmp_path / "clone"
    cfg = _cfg(str(upstream.resolve()), clone_dest)
    ensure_startup_repo_ready(cfg=cfg)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(tmp_path / "backups"))

    _warnings, copied = run_init_home("bash", yes=True, cfg=cfg)
    assert ".bashrc" in copied
    assert (home / ".bashrc").read_text(encoding="utf8") == "from_repo\n"


def test_run_init_home_skips_identical(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream, bashrc="same\n")
    clone_dest = tmp_path / "clone"
    cfg = _cfg(str(upstream.resolve()), clone_dest)
    ensure_startup_repo_ready(cfg=cfg)

    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("same\n", encoding="utf8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(tmp_path / "backups"))

    _warnings, copied = run_init_home("bash", yes=True, cfg=cfg)
    assert copied == []


def test_run_init_home_creates_backup_before_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    upstream = tmp_path / "upstream"
    _create_upstream_repo(upstream, bashrc="new_content\n")
    clone_dest = tmp_path / "clone"
    cfg = _cfg(str(upstream.resolve()), clone_dest)
    ensure_startup_repo_ready(cfg=cfg)

    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("old_content\n", encoding="utf8")
    bk = tmp_path / "backups"
    bk.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELLENV_BACKUP_DIR", str(bk))

    _warnings, copied = run_init_home("bash", yes=True, cfg=cfg)
    assert ".bashrc" in copied
    assert (home / ".bashrc").read_text(encoding="utf8") == "new_content\n"
    archives = list(bk.glob("shellenv-backup-*.tar.gz"))
    assert len(archives) == 1
