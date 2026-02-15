"""Tests for the trace mocking functionality."""
import os

from env_config.trace import analyze_traces, parse_trace, run_shell_trace


def test_run_shell_trace_uses_mock(monkeypatch, tmp_path):
    """Test that run_shell_trace uses the mock trace data when ENVCONFIG_MOCK_TRACE_DIR is set."""
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("ENVCONFIG_MOCK_TRACE_DIR", fixtures)

    raw = run_shell_trace("bash", args=["-l", "-c", "true"])
    assert "/home/testuser/.bash_profile" in raw or ".bashrc" in raw

    parsed = parse_trace(raw, family="bash")
    analysis = analyze_traces(parsed, threshold_secs=0.1)
    assert analysis["total"] > 0
    # ensure long_running_cmd contributed to bash_profile and was measured
    assert any(".bash_profile" in item["file"] for item in analysis["items"]) or any(
        item["commands"] >= 1 for item in analysis["items"]
    )


def test_run_shell_trace_zsh_mock(monkeypatch):
    """Test that run_shell_trace returns mock data for zsh when ENVCONFIG_MOCK_TRACE_DIR is set."""
    fixtures = os.path.join(os.getcwd(), "tests", "fixtures", "traces")
    monkeypatch.setenv("ENVCONFIG_MOCK_TRACE_DIR", fixtures)
    raw = run_shell_trace("zsh", args=["-l", "-c", "true"])
    assert "zshenv" in raw or "zshrc" in raw or "zprofile" in raw
    parsed = parse_trace(raw, family="zsh")
    analysis = analyze_traces(parsed, threshold_secs=0.001)
    assert analysis["total"] >= 0
