"""Tests for hobees.core.provider_detector."""

from __future__ import annotations

import socket

import pytest

from hobees.core.provider_detector import (
    _CLOUD_PROVIDERS,
    _port_open,
    detect_available_providers,
    find_detection_spec,
    is_first_launch,
    mark_detected,
)


# ---------------------------------------------------------------------------
# _port_open
# ---------------------------------------------------------------------------


def test_port_open_returns_true_when_connection_succeeds(monkeypatch):
    """_port_open returns True when create_connection does not raise."""

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: _FakeConn())
    assert _port_open("localhost", 11434) is True


def test_port_open_returns_false_on_oserror(monkeypatch):
    """_port_open returns False when connection is refused."""

    def _raise(*a, **kw):
        raise OSError("Connection refused")

    monkeypatch.setattr(socket, "create_connection", _raise)
    assert _port_open("localhost", 11434) is False


# ---------------------------------------------------------------------------
# detect_available_providers — env-var branch
# ---------------------------------------------------------------------------

# Read from the catalogue so a new default can never drift out of the tests.
_ALL_CLOUD_KEYS = tuple(spec["env_var"] for spec in _CLOUD_PROVIDERS)


def _no_ports(monkeypatch):
    monkeypatch.setattr("hobees.core.provider_detector._port_open", lambda *a, **kw: False)


def test_detect_openai_key(monkeypatch):
    """Detects OpenAI when OPENAI_API_KEY is set."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    _no_ports(monkeypatch)

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "openai-main" in aliases
    assert "anthropic-main" not in aliases


def test_detect_anthropic_key(monkeypatch):
    """Detects Anthropic when ANTHROPIC_API_KEY is set."""
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    _no_ports(monkeypatch)

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "anthropic-main" in aliases


def test_detect_gemini_key(monkeypatch):
    """Detects Gemini when GEMINI_API_KEY is set."""
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    _no_ports(monkeypatch)

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "gemini-main" in aliases


def test_detect_multiple_cloud_keys(monkeypatch):
    """Detects multiple cloud providers when multiple keys are set."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    _no_ports(monkeypatch)

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "openai-main" in aliases
    assert "anthropic-main" in aliases


def test_detect_no_keys_no_ports(monkeypatch):
    """Returns empty list when nothing is available."""
    for k in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    _no_ports(monkeypatch)

    assert detect_available_providers() == []


# ---------------------------------------------------------------------------
# detect_available_providers — local port branch
# ---------------------------------------------------------------------------


def test_detect_ollama_port(monkeypatch):
    """Detects Ollama when port 11434 is open."""
    for k in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        "hobees.core.provider_detector._port_open",
        lambda host, port, **kw: port == 11434,
    )

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "ollama-local" in aliases
    assert "llamacpp-local" not in aliases


def test_detect_llamacpp_port(monkeypatch):
    """Detects llama-server when port 8080 is open."""
    for k in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        "hobees.core.provider_detector._port_open",
        lambda host, port, **kw: port == 8080,
    )

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "llamacpp-local" in aliases


def test_detect_mixed_cloud_and_local(monkeypatch):
    """Detects both cloud and local providers simultaneously."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        "hobees.core.provider_detector._port_open",
        lambda host, port, **kw: port == 11434,
    )

    aliases = [r["alias"] for r in detect_available_providers()]
    assert "openai-main" in aliases
    assert "ollama-local" in aliases


# ---------------------------------------------------------------------------
# Sentinel / first-launch helpers
# ---------------------------------------------------------------------------


def test_is_first_launch_true_when_no_sentinel(tmp_path, monkeypatch):
    """is_first_launch returns True when the sentinel file does not exist."""
    sentinel = tmp_path / ".detected"
    monkeypatch.setattr("hobees.core.provider_detector._SENTINEL_FILE", sentinel)
    assert is_first_launch() is True


def test_is_first_launch_false_after_mark(tmp_path, monkeypatch):
    """is_first_launch returns False after mark_detected is called."""
    sentinel = tmp_path / ".detected"
    monkeypatch.setattr("hobees.core.provider_detector._SENTINEL_FILE", sentinel)
    assert is_first_launch() is True
    mark_detected()
    assert is_first_launch() is False


# ---------------------------------------------------------------------------
# Returned dict structure
# ---------------------------------------------------------------------------


def test_candidate_dict_has_required_keys(monkeypatch):
    """Each candidate dict contains the keys needed for provider registration."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    _no_ports(monkeypatch)

    results = detect_available_providers()
    assert results, "Expected at least one candidate"

    required_keys = {"alias", "provider_type", "api_key_env", "default_model", "source_label"}
    for candidate in results:
        missing = required_keys - candidate.keys()
        assert not missing, f"Candidate {candidate['alias']!r} missing keys: {missing}"


def test_env_var_key_not_in_returned_dict(monkeypatch):
    """The internal 'env_var' key is stripped from returned cloud candidates."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    _no_ports(monkeypatch)

    results = detect_available_providers()
    for candidate in results:
        assert "env_var" not in candidate, "Internal 'env_var' key should be stripped"

# ---------------------------------------------------------------------------
# DeepSeek default
# ---------------------------------------------------------------------------


def test_deepseek_is_a_detection_default(monkeypatch):
    for key in _ALL_CLOUD_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    _no_ports(monkeypatch)

    candidates = {c["alias"]: c for c in detect_available_providers()}
    assert candidates["deepseek-main"]["base_url"] == "https://api.deepseek.com/v1"
    assert candidates["deepseek-main"]["api_key_env"] == "DEEPSEEK_API_KEY"


def test_find_detection_spec_returns_the_candidate_shape():
    spec = find_detection_spec("deepseek-main")
    assert spec and spec["alias"] == "deepseek-main"
    assert "env_var" not in spec and "host" not in spec and "port" not in spec
    assert find_detection_spec("not-a-candidate") is None

def test_local_detection_catalog_has_no_strata_entry():
    """Strata was dropped from the detection defaults on purpose."""
    from hobees.core.provider_detector import _LOCAL_PROVIDERS

    aliases = {spec["alias"] for spec in _LOCAL_PROVIDERS}
    assert aliases == {"ollama-local", "llamacpp-local", "lmstudio-local"}
    assert "strata-local" not in aliases
