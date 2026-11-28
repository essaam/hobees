from types import SimpleNamespace

import requests

from hobees.core.model_discovery import _MODEL_CACHE, fetch_provider_models


def test_refresh_cache_bypasses_cached_provider_models(monkeypatch):
    _MODEL_CACHE.clear()
    provider = SimpleNamespace(
        provider_type="openai_compatible",
        base_url="http://localhost:8080",
        api_key_env="NONE",
    )
    calls = []
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": [{"id": "model-a"}, {"id": "model-b"}]},
    )

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return response

    monkeypatch.setattr(requests, "get", fake_get)

    assert fetch_provider_models(provider) == ["model-a", "model-b"]
    assert fetch_provider_models(provider) == ["model-a", "model-b"]
    assert len(calls) == 1

    assert fetch_provider_models(provider, refresh_cache=True) == ["model-a", "model-b"]
    assert len(calls) == 2


def test_resolve_model_name_follows_the_order_the_ui_shows():
    from types import SimpleNamespace

    from hobees.core.model_discovery import resolve_model_name

    provider = SimpleNamespace(
        default_model="llama3",
        assistant_model="llama3.1-lab",
        available_models=["llama3.2", "llama3.3"],
    )
    # What was asked for wins, then the default, then the assistant model, then detection.
    assert resolve_model_name(provider, "qwen") == "qwen"
    assert resolve_model_name(provider, "") == "llama3"
    assert resolve_model_name(provider, None) == "llama3"

    bare = SimpleNamespace(default_model=None, assistant_model="small", available_models=["detected"])
    assert resolve_model_name(bare, "") == "small"

    nothing = SimpleNamespace(default_model=None, assistant_model=None, available_models=[])
    assert resolve_model_name(nothing, "") is None
