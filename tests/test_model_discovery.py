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
