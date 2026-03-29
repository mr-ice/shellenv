from shellenv.config import _load_cfg_safe, default_config_dict, load_config


def test_load_config_safe(tmp_path):
    """Malformed TOML is treated as empty by _load_cfg_safe."""
    p = tmp_path / "bad.toml"
    p.write_text("-")
    assert _load_cfg_safe(p) == {}


def test_load_config_migrates_allow_non_repo(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[compose]\nallow_non_repo = "true"\n', encoding="utf8")
    data = load_config(p)
    assert data["compose"]["allow_dirty_or_off_main"] == "true"
    assert "allow_non_repo" not in data["compose"]


def test_default_config_dict():
    assert default_config_dict() == {
        "trace": {"threshold_secs": None, "threshold_percent": None},
        "repo": {"url": None, "destination": None},
        "compose": {
            "paths": [],
            "shell_rc_files": [],
            "allow_dirty_or_off_main": "false",
            "allowed_path_kinds": ["repo", "directory"],
        },
        "shellenv": {"tool_repo_path": "~/.shellenv"},
    }
