"""Tests for config schema coercion and validation helpers."""

import pytest

from shellenv.config import coerce_value, validate_config, validate_value

# -- coerce_value -----------------------------------------------------------


class TestCoerceFloat:
    """Tests for coercing strings to float types."""

    def test_plain_float(self):
        assert coerce_value("3.14", "float") == pytest.approx(3.14)

    def test_integer_string_as_float(self):
        assert coerce_value("7", "float") == 7.0

    def test_invalid_float(self):
        with pytest.raises(ValueError, match="expected a float"):
            coerce_value("abc", "float")


class TestCoerceInt:
    """Tests for coercing strings to int."""

    def test_plain_int(self):
        assert coerce_value("42", "int") == 42

    def test_invalid_int(self):
        with pytest.raises(ValueError, match="expected an integer"):
            coerce_value("3.5", "int")

    def test_non_numeric_int(self):
        with pytest.raises(ValueError, match="expected an integer"):
            coerce_value("abc", "int")


class TestCoerceString:
    """Tests for coercing strings to string (passthrough)."""

    def test_passthrough(self):
        assert coerce_value("hello", "string") == "hello"

    def test_empty_string(self):
        assert coerce_value("", "string") == ""


class TestCoerceFloatOrNull:
    """Tests for coercing strings to float-or-null."""

    def test_null_token(self):
        assert coerce_value("null", "float_or_null") is None
        assert coerce_value("none", "float_or_null") is None
        assert coerce_value("", "float_or_null") is None

    def test_float_value(self):
        assert coerce_value("0.05", "float_or_null") == pytest.approx(0.05)

    def test_invalid(self):
        with pytest.raises(ValueError, match="expected a float"):
            coerce_value("abc", "float_or_null")


class TestCoerceStringOrNull:
    """Tests for coercing strings to string-or-null."""

    def test_null_token(self):
        assert coerce_value("null", "string_or_null") is None
        assert coerce_value("None", "string_or_null") is None

    def test_string_value(self):
        assert coerce_value("/tmp/repo", "string_or_null") == "/tmp/repo"


class TestCoerceListOfStrings:
    """Tests for coercing comma-separated strings to list."""

    def test_comma_separated(self):
        assert coerce_value("/a, /b, /c", "list_of_strings") == ["/a", "/b", "/c"]

    def test_single_item(self):
        assert coerce_value("/only", "list_of_strings") == ["/only"]

    def test_empty(self):
        assert coerce_value("", "list_of_strings") == []


class TestCoerceUnknownType:
    """Tests for unknown value_type."""

    def test_unknown_type(self):
        with pytest.raises(ValueError, match="unknown value_type"):
            coerce_value("x", "bogus_type")


# -- validate_value ---------------------------------------------------------


class TestValidateValue:
    """Tests for validate_value against each type."""

    def test_float_accepts_int_and_float(self):
        assert validate_value(1.5, "float") is True
        assert validate_value(3, "float") is True

    def test_float_rejects_string(self):
        assert validate_value("1.5", "float") is False

    def test_float_rejects_bool(self):
        assert validate_value(True, "float") is False

    def test_int_accepts_int(self):
        assert validate_value(20, "int") is True

    def test_int_rejects_float(self):
        assert validate_value(1.5, "int") is False

    def test_int_rejects_bool(self):
        assert validate_value(True, "int") is False

    def test_string(self):
        assert validate_value("hello", "string") is True
        assert validate_value(42, "string") is False

    def test_float_or_null(self):
        assert validate_value(None, "float_or_null") is True
        assert validate_value(0.05, "float_or_null") is True
        assert validate_value("x", "float_or_null") is False

    def test_string_or_null(self):
        assert validate_value(None, "string_or_null") is True
        assert validate_value("url", "string_or_null") is True
        assert validate_value(123, "string_or_null") is False

    def test_list_of_strings(self):
        assert validate_value(["/a", "/b"], "list_of_strings") is True
        assert validate_value([], "list_of_strings") is True
        assert validate_value([1, 2], "list_of_strings") is False
        assert validate_value("not a list", "list_of_strings") is False

    def test_rejects_unknown(self):
        assert validate_value(("a",), "set") is False


# -- validate_config --------------------------------------------------------


class TestValidateConfig:
    """Tests for full config dict validation."""

    def test_valid_config(self):
        data = {"trace": {"threshold_secs": 0.5, "threshold_percent": 10.0}}
        assert validate_config(data) == []

    def test_unknown_section(self):
        data = {"bogus": {"key": 1}}
        errors = validate_config(data)
        assert any("unknown section 'bogus'" in e for e in errors)

    def test_unknown_subkey(self):
        data = {"trace": {"threshold_secs": 0.5, "extra_key": True}}
        errors = validate_config(data)
        assert any("unknown key 'trace.extra_key'" in e for e in errors)

    def test_wrong_type(self):
        data = {"trace": {"threshold_secs": "not_a_float"}}
        errors = validate_config(data)
        assert any("expected float_or_null" in e for e in errors)

    def test_empty_config_is_valid(self):
        assert validate_config({}) == []

    def test_partial_config_is_valid(self):
        data = {"repo": {"url": "https://example.com"}}
        assert validate_config(data) == []
