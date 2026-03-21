"""Tests for the shared modes module."""

from shellctl.modes import (
    INVOCATION_MODES,
    mode_to_args,
    resolve_modes,
)


def test_resolve_modes_none_returns_all():
    assert resolve_modes(None) == list(INVOCATION_MODES)


def test_resolve_modes_all_returns_all():
    assert resolve_modes("all") == list(INVOCATION_MODES)


def test_resolve_modes_short_tags():
    assert resolve_modes("li") == ["login_interactive"]
    assert resolve_modes("ln") == ["login_noninteractive"]
    assert resolve_modes("ni") == ["nonlogin_interactive"]
    assert resolve_modes("nn") == ["nonlogin_noninteractive"]


def test_resolve_modes_full_names():
    assert resolve_modes("login_interactive") == ["login_interactive"]
    assert resolve_modes("login_noninteractive") == ["login_noninteractive"]


def test_resolve_modes_list():
    assert resolve_modes(["li", "nn"]) == ["login_interactive", "nonlogin_noninteractive"]


def test_mode_to_args_login_interactive():
    assert mode_to_args("zsh", "login_interactive") == ["-l", "-i", "-c", ":"]


def test_mode_to_args_login_noninteractive():
    assert mode_to_args("bash", "login_noninteractive") == ["-l", "-c", ":"]


def test_mode_to_args_nonlogin_noninteractive():
    assert mode_to_args("tcsh", "nonlogin_noninteractive") == ["-c", ":"]
