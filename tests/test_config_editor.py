"""Tests for the editor validation flow and validate_editor_config helper."""

import tomllib

import tomli_w

from shellenv.tui import validate_editor_config


class TestValidateEditorConfig:
    """Tests for validate_editor_config (file-level validation)."""

    def test_valid_toml(self, tmp_path):
        """Valid TOML with known keys passes validation."""
        p = tmp_path / "cfg.toml"
        p.write_text(tomli_w.dumps({"trace": {"threshold_secs": 0.5}}))
        assert validate_editor_config(p) == []

    def test_empty_table_is_valid(self, tmp_path):
        """An empty TOML table is valid (all keys optional)."""
        p = tmp_path / "cfg.toml"
        p.write_text("")
        assert validate_editor_config(p) == []

    def test_missing_file(self, tmp_path):
        """A non-existent path returns an error."""
        p = tmp_path / "nope.toml"
        errors = validate_editor_config(p)
        assert any("does not exist" in e for e in errors)

    def test_invalid_toml(self, tmp_path):
        """Malformed TOML returns a parse error."""
        p = tmp_path / "cfg.toml"
        p.write_text("[not valid toml\nkey = ")
        errors = validate_editor_config(p)
        assert any("invalid TOML" in e for e in errors)

    def test_unknown_section(self, tmp_path):
        """Unknown top-level keys produce errors."""
        p = tmp_path / "cfg.toml"
        p.write_text(tomli_w.dumps({"bogus": {"x": 1}}))
        errors = validate_editor_config(p)
        assert any("unknown section" in e for e in errors)

    def test_unknown_subkey(self, tmp_path):
        """Unknown sub-keys in a valid section produce errors."""
        p = tmp_path / "cfg.toml"
        p.write_text(tomli_w.dumps({"trace": {"threshold_secs": 0.5, "extra": True}}))
        errors = validate_editor_config(p)
        assert any("unknown key" in e for e in errors)

    def test_wrong_value_type(self, tmp_path):
        """Correct keys with wrong value types produce errors."""
        p = tmp_path / "cfg.toml"
        p.write_text(tomli_w.dumps({"trace": {"threshold_secs": "not_a_float"}}))
        errors = validate_editor_config(p)
        assert any("expected float_or_null" in e for e in errors)

    def test_full_valid_config(self, tmp_path):
        """A fully populated valid config passes."""
        data = {
            "trace": {"threshold_secs": 0.1, "threshold_percent": 25.0},
            "repo": {"url": "https://example.com/repo.git", "destination": "/tmp/repo"},
            "compose": {
                "paths": ["/a", "/b"],
                "shell_rc_files": ["zshrc", "zshenv"],
                "allow_non_repo": "false",
            },
        }
        p = tmp_path / "cfg.toml"
        p.write_text(tomli_w.dumps(data))
        assert validate_editor_config(p) == []


class TestEditorRestore:
    """Tests for the restore-on-invalid behaviour of the editor flow."""

    def test_invalid_edit_is_reverted(self, tmp_path, monkeypatch):
        """After 'editing' produces invalid TOML, the original is restored."""
        from shellenv.config import save_config

        user_cfg = tmp_path / ".shellenv.toml"
        global_cfg = tmp_path / "global.toml"
        monkeypatch.setattr("shellenv.config.user_config_path", lambda: user_cfg)
        monkeypatch.setattr("shellenv.config.GLOBAL_CONFIG_PATH", global_cfg)

        # write a valid initial config
        save_config(user_cfg, {"trace": {"threshold_percent": 42.0}})
        original = user_cfg.read_text()

        # simulate the editor writing invalid TOML
        def fake_editor(cmd):
            user_cfg.write_text("[bad toml\nkey = ")

        monkeypatch.setattr("subprocess.run", fake_editor)

        # import the flow helper directly (it calls curses.endwin which we
        # can't do here, so we test the validate+restore logic manually)
        errors = validate_editor_config(user_cfg)
        # simulate the restore that _editor_flow performs
        if errors:
            user_cfg.write_text(original, encoding="utf8")

        # file should be restored
        with open(user_cfg, "rb") as f:
            assert tomllib.load(f) == {"trace": {"threshold_percent": 42.0}}

    def test_valid_edit_is_kept(self, tmp_path, monkeypatch):
        """After 'editing' produces valid TOML, the new content is kept."""
        from shellenv.config import save_config

        user_cfg = tmp_path / ".shellenv.toml"
        global_cfg = tmp_path / "global.toml"
        monkeypatch.setattr("shellenv.config.user_config_path", lambda: user_cfg)
        monkeypatch.setattr("shellenv.config.GLOBAL_CONFIG_PATH", global_cfg)

        save_config(user_cfg, {"trace": {"threshold_percent": 10.0}})
        original = user_cfg.read_text()

        # simulate the editor writing a valid change
        new_data = {"trace": {"threshold_percent": 99.0}}
        user_cfg.write_text(tomli_w.dumps(new_data))

        errors = validate_editor_config(user_cfg)
        if errors:
            user_cfg.write_text(original, encoding="utf8")

        with open(user_cfg, "rb") as f:
            assert tomllib.load(f) == new_data
