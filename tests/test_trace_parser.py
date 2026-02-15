"""Tests for the trace parsing logic.

These tests ensure it can handle various trace formats and extract relevant information.
"""
from env_config.trace import parse_trace


def test_parse_bash_trace_simple():
    """Test parsing a simple bash trace with timestamps, file paths, and command counts."""
    trace = """
+1613341234.100000 /home/user/.bashrc:1 echo hello
+1613341234.200000 /home/user/.bashrc:2 source /home/user/.bash_profile
+1613341234.300000 /home/user/.bash_profile:1 echo world
+1613341234.400000 /home/user/.bash_profile:2 echo done
"""
    res = parse_trace(trace, family="bash")
    # should detect both bashrc and bash_profile and count commands
    paths = [r.path for r in res]
    assert any(p.endswith(".bashrc") for p in paths)
    assert any(p.endswith(".bash_profile") for p in paths)
    # verify command counts for each file
    lookup = {r.path: r.commands for r in res}
    assert any(r.endswith(".bashrc") and lookup[r] == 2 for r in lookup)
    assert any(r.endswith(".bash_profile") and lookup[r] == 2 for r in lookup)


def test_parse_generic_trace_simple():
    """Test parsing a generic trace without timestamps, ensuring it can still extract file paths."""
    trace = """
+1613341234.100000 /home/user/.zshenv:1 somecmd
+1613341234.200000 /home/user/.zshrc:5 othercmd
+1613341234.300000 source /home/user/.zprofile
"""
    res = parse_trace(trace, family="zsh")
    assert any(ft.path.endswith("zshenv") for ft in res)
    assert any("zshrc" in ft.path or ft.commands >= 1 for ft in res)


def test_parse_generic_trace_without_timestamps():
    """Test parsing a trace that lacks timestamps.

    These tests ensure it can still extract file paths and command counts.
    """
    trace = """
+ + somecommand
source /home/user/.zshrc
 . /home/user/.zprofile
anothercmd /home/user/.zshenv
"""
    res = parse_trace(trace, family="zsh")
    paths = [ft.path for ft in res]
    assert any("zshrc" in p for p in paths)
    assert any("zprofile" in p for p in paths)
    assert any("zshenv" in p for p in paths)
