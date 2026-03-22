from shellenv.config import _load_cfg_safe, default_config_dict


def test_load_config_safe(tmp_path):
    """Malformed TOML is treated as empty by _load_cfg_safe."""
    p = tmp_path / "bad.toml"
    p.write_text("-")
    assert _load_cfg_safe(p) == {}


def test_default_config_dict():
    assert default_config_dict() == {
        "trace": {"threshold_secs": None, "threshold_percent": None},
        "repo": {"url": None, "destination": None},
        "compose": {"paths": [], "shell_rc_files": [], "allow_non_repo": "false"},
    }
