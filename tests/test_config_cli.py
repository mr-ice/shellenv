"""Tests for the CLI ``config`` subcommand (show/get/set/reset)."""

import tomllib

import pytest

from shellctl.cli import main


@pytest.fixture()
def _isolate(tmp_path, monkeypatch):
    """Redirect config paths to tmp_path so tests are hermetic."""
    user_cfg = tmp_path / ".shellctl.toml"
    global_cfg = tmp_path / "global.toml"
    monkeypatch.setattr("shellctl.config.user_config_path", lambda: user_cfg)
    monkeypatch.setattr("shellctl.config.GLOBAL_CONFIG_PATH", global_cfg)
    return user_cfg, global_cfg


# -- config show ------------------------------------------------------------


class TestConfigShow:
    """Tests for ``shellctl config show``."""

    def test_show_prints_all_keys(self, _isolate, capsys):
        rc = main(["config", "show"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "trace.threshold_secs" in out
        assert "trace.threshold_percent" in out
        assert "repo.url" in out
        assert "compose.paths" in out

    def test_show_single_key(self, _isolate, capsys):
        main(["config", "set", "compose.paths", "/a", "/b"])
        rc = main(["config", "show", "compose.paths"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "['/a', '/b']"

    def test_show_unknown_key(self, _isolate, capsys):
        rc = main(["config", "show", "no.such.key"])
        assert rc == 1
        assert "unknown config key" in capsys.readouterr().err


# -- config get -------------------------------------------------------------


class TestConfigGet:
    """Tests for ``shellctl config get``."""

    def test_get_known_key(self, _isolate, capsys):
        rc = main(["config", "get", "trace.threshold_percent"])
        assert rc == 0
        assert "None" in capsys.readouterr().out

    def test_get_unknown_key(self, _isolate, capsys):
        rc = main(["config", "get", "no.such.key"])
        assert rc == 1
        assert "unknown config key" in capsys.readouterr().err

    def test_get_reflects_set(self, _isolate, capsys):
        main(["config", "set", "trace.threshold_percent", "50"])
        rc = main(["config", "get", "trace.threshold_percent"])
        assert rc == 0
        assert "50" in capsys.readouterr().out


# -- config set -------------------------------------------------------------


class TestConfigSet:
    """Tests for ``shellctl config set``."""

    def test_set_valid_float(self, _isolate, capsys):
        rc = main(["config", "set", "trace.threshold_percent", "30"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["trace"]["threshold_percent"] == pytest.approx(30.0)

    def test_set_invalid_type(self, _isolate, capsys):
        rc = main(["config", "set", "trace.threshold_percent", "abc"])
        assert rc == 1
        assert "error" in capsys.readouterr().err.lower()

    def test_set_unknown_key(self, _isolate, capsys):
        rc = main(["config", "set", "bogus.key", "1"])
        assert rc == 1
        assert "unknown config key" in capsys.readouterr().err

    def test_set_float_or_null(self, _isolate, capsys):
        rc = main(["config", "set", "trace.threshold_secs", "0.05"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["trace"]["threshold_secs"] == pytest.approx(0.05)

    def test_set_null(self, _isolate, capsys):
        main(["config", "set", "trace.threshold_secs", "0.05"])
        rc = main(["config", "set", "trace.threshold_secs", "null"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        # None values are omitted in TOML; key should be absent
        assert "threshold_secs" not in data.get("trace", {})

    def test_set_list(self, _isolate, capsys):
        rc = main(["config", "set", "compose.paths", "/a", "/b"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["compose"]["paths"] == ["/a", "/b"]

    def test_set_list_append(self, _isolate, capsys):
        main(["config", "set", "compose.paths", "/a"])
        rc = main(["config", "set", "compose.paths", "/b", "/c", "--append"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["compose"]["paths"] == ["/a", "/b", "/c"]

    def test_set_string_or_null(self, _isolate, capsys):
        rc = main(["config", "set", "repo.url", "https://example.com/repo.git"])
        assert rc == 0
        user_cfg, _ = _isolate
        with open(user_cfg, "rb") as f:
            data = tomllib.load(f)
        assert data["repo"]["url"] == "https://example.com/repo.git"


# -- config reset -----------------------------------------------------------


class TestConfigReset:
    """Tests for ``shellctl config reset``."""

    def test_reset_reverts_to_default(self, _isolate, capsys):
        main(["config", "set", "trace.threshold_percent", "99"])
        rc = main(["config", "reset", "trace.threshold_percent"])
        assert rc == 0
        # get should now show default
        main(["config", "get", "trace.threshold_percent"])
        assert "None" in capsys.readouterr().out

    def test_reset_unknown_key(self, _isolate, capsys):
        rc = main(["config", "reset", "bogus.key"])
        assert rc == 1
        assert "unknown config key" in capsys.readouterr().err


# -- config (no subcommand) -------------------------------------------------


class TestConfigNoSubcmd:
    """Tests for ``shellctl config`` with no sub-subcommand."""

    def test_prints_usage(self, _isolate, capsys):
        rc = main(["config"])
        assert rc == 1
        assert "usage" in capsys.readouterr().err.lower()


class TestConfigInitGlobal:
    """Tests for ``shellctl config init-global``."""

    def test_writes_template(self, _isolate, tmp_path, capsys):
        out_path = tmp_path / "site.toml"
        rc = main(["config", "init-global", "--path", str(out_path)])
        assert rc == 0
        assert out_path.exists()
        text = out_path.read_text(encoding="utf8")
        assert "[trace]" in text
        assert "threshold_secs" in text
        # nested key name should be leaf in section
        assert "compose.paths" not in text

    def test_requires_force_to_overwrite(self, _isolate, tmp_path, capsys):
        out_path = tmp_path / "site.toml"
        out_path.write_text("[trace]\n", encoding="utf8")
        rc = main(["config", "init-global", "--path", str(out_path)])
        assert rc == 1
        assert "already exists" in capsys.readouterr().err


class TestConfigKeys:
    """Tests for ``shellctl config keys``."""

    def test_keys_prints_metadata_table(self, _isolate, capsys):
        rc = main(["config", "keys"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "trace.threshold_secs" in out
        assert "float_or_null" in out
        assert "Flag files taking longer than N seconds" in out
