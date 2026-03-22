"""Tests for config get/set/reset/show operations and nested-dict helpers."""

import pytest
import tomli_w

from shellenv.config import (
    _MISSING,
    CONFIG_SCHEMA,
    config_get,
    config_reset,
    config_set,
    config_show,
    delete_nested,
    get_nested,
    global_config_path,
    load_merged_config,
    render_default_config_template,
    set_nested,
    write_default_config_template,
)

# -- nested-dict helpers ----------------------------------------------------


class TestGetNested:
    """Tests for get_nested."""

    def test_simple_key(self):
        assert get_nested({"a": {"b": 1}}, "a.b") == 1

    def test_missing_key_returns_sentinel(self):
        assert get_nested({"a": {}}, "a.b") is _MISSING

    def test_missing_section_returns_sentinel(self):
        assert get_nested({}, "a.b") is _MISSING

    def test_single_level(self):
        assert get_nested({"x": 5}, "x") == 5


class TestSetNested:
    """Tests for set_nested."""

    def test_creates_intermediates(self):
        d: dict = {}
        set_nested(d, "a.b.c", 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_overwrites_existing(self):
        d = {"a": {"b": 1}}
        set_nested(d, "a.b", 2)
        assert d["a"]["b"] == 2


class TestDeleteNested:
    """Tests for delete_nested."""

    def test_delete_existing(self):
        d = {"a": {"b": 1, "c": 2}}
        assert delete_nested(d, "a.b") is True
        assert d == {"a": {"c": 2}}

    def test_delete_cleans_empty_parents(self):
        d = {"a": {"b": 1}}
        assert delete_nested(d, "a.b") is True
        assert d == {}

    def test_delete_missing_returns_false(self):
        assert delete_nested({}, "a.b") is False

    def test_delete_missing_leaf_returns_false(self):
        d = {"a": {"c": 1}}
        assert delete_nested(d, "a.b") is False


# -- fixtures ---------------------------------------------------------------


@pytest.fixture()
def _isolate_config(tmp_path, monkeypatch):
    """Point config paths to tmp_path so tests don't touch real files."""
    user_cfg = tmp_path / ".shellenv.toml"
    global_cfg = tmp_path / "global.toml"
    monkeypatch.setattr("shellenv.config.user_config_path", lambda: user_cfg)
    monkeypatch.setattr("shellenv.config.GLOBAL_CONFIG_PATH", global_cfg)
    return user_cfg, global_cfg


# -- config_get -------------------------------------------------------------


class TestConfigGet:
    """Tests for config_get."""

    def test_default_value(self, _isolate_config):
        assert config_get("trace.threshold_percent") is None

    def test_unknown_key_raises(self, _isolate_config):
        with pytest.raises(KeyError, match="unknown config key"):
            config_get("bogus.key")

    def test_reads_user_value(self, _isolate_config):
        user_cfg, _ = _isolate_config
        user_cfg.write_text(tomli_w.dumps({"trace": {"threshold_percent": 50}}))
        assert config_get("trace.threshold_percent") == 50


# -- config_set -------------------------------------------------------------


class TestConfigSet:
    """Tests for config_set."""

    def test_set_and_get_roundtrip(self, _isolate_config):
        config_set("trace.threshold_percent", 30.0)
        assert config_get("trace.threshold_percent") == 30.0

    def test_unknown_key_raises(self, _isolate_config):
        with pytest.raises(KeyError, match="unknown config key"):
            config_set("bogus.key", 1)

    def test_wrong_type_raises(self, _isolate_config):
        with pytest.raises(ValueError, match="expects float_or_null"):
            config_set("trace.threshold_percent", "not_float")

    def test_set_float_or_null(self, _isolate_config):
        config_set("trace.threshold_secs", 0.05)
        assert config_get("trace.threshold_secs") == pytest.approx(0.05)

    def test_set_null_value(self, _isolate_config):
        config_set("trace.threshold_secs", 0.05)
        config_set("trace.threshold_secs", None)
        assert config_get("trace.threshold_secs") is None

    def test_set_list(self, _isolate_config):
        config_set("compose.paths", ["/a", "/b"])
        assert config_get("compose.paths") == ["/a", "/b"]


# -- config_reset -----------------------------------------------------------


class TestConfigReset:
    """Tests for config_reset."""

    def test_reset_reverts_to_default(self, _isolate_config):
        config_set("trace.threshold_percent", 50.0)
        config_reset("trace.threshold_percent")
        assert config_get("trace.threshold_percent") is None

    def test_reset_unknown_key_raises(self, _isolate_config):
        with pytest.raises(KeyError, match="unknown config key"):
            config_reset("bogus.key")

    def test_reset_unset_key_is_noop(self, _isolate_config):
        config_reset("trace.threshold_percent")  # should not raise


# -- config_show ------------------------------------------------------------


class TestConfigShow:
    """Tests for config_show."""

    def test_returns_all_schema_keys(self, _isolate_config):
        values = config_show()
        assert set(values.keys()) == set(CONFIG_SCHEMA.keys())

    def test_reflects_user_values(self, _isolate_config):
        config_set("trace.threshold_percent", 99.0)
        values = config_show()
        assert values["trace.threshold_percent"] == 99.0


# -- load_merged_config (append strategy) -----------------------------------


class TestMergeAppend:
    """Tests for list append merge strategy."""

    def test_user_list_appends_to_global(self, _isolate_config):
        _, global_cfg = _isolate_config
        global_cfg.write_text(tomli_w.dumps({"compose": {"paths": ["/global"]}}))
        user_cfg, _ = _isolate_config
        user_cfg.write_text(tomli_w.dumps({"compose": {"paths": ["/user"]}}))
        merged = load_merged_config()
        assert merged["compose"]["paths"] == ["/global", "/user"]

    def test_user_list_without_global(self, _isolate_config):
        user_cfg, _ = _isolate_config
        user_cfg.write_text(tomli_w.dumps({"compose": {"paths": ["/user"]}}))
        merged = load_merged_config()
        assert merged["compose"]["paths"] == ["/user"]

    def test_global_list_without_user(self, _isolate_config):
        _, global_cfg = _isolate_config
        global_cfg.write_text(tomli_w.dumps({"compose": {"paths": ["/global"]}}))
        merged = load_merged_config()
        assert merged["compose"]["paths"] == ["/global"]


class TestGlobalTemplate:
    """Tests for global template helpers."""

    def test_render_contains_sections(self, _isolate_config):
        text = render_default_config_template()
        assert "[trace]" in text
        assert "[compose]" in text

    def test_write_template_file(self, _isolate_config, tmp_path):
        p = tmp_path / "shellenv.toml"
        write_default_config_template(p)
        assert p.exists()

    def test_global_path_env_override(self, _isolate_config, monkeypatch, tmp_path):
        p = tmp_path / "site.toml"
        monkeypatch.setenv("SHELLENV_GLOBAL_CONFIG_PATH", str(p))
        assert global_config_path() == p
