"""Provider model auto-discovery via HTTP requests.

Supports local (llama.cpp, Ollama, vLLM, LM Studio) and remote (OpenAI, Anthropic, Google Gemini, OpenRouter) providers.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Tuple, Union

from rich.console import Console

from hobees.cli.icons import SUCCESS, WARN

console = Console()

_MODEL_CACHE: Dict[Tuple[str, str, str], List[str]] = {}


def fetch_provider_models(
    provider_row: Union[dict, object],
    refresh_cache: bool = False,
) -> List[str]:
    """Fetch available models from a provider.

    Args:
        provider_row: dict or ORM object with keys: alias, provider_type, base_url, api_key_env
        refresh_cache: whether to force a fresh request

    Returns:
        List of model names, or empty list if unavailable
    """
    # Handle both dict and ORM object
    if hasattr(provider_row, "provider_type"):
        provider_type = provider_row.provider_type
        base_url = (provider_row.base_url or "").rstrip("/")
        api_key_env = provider_row.api_key_env or "NONE"
    else:
        provider_type = provider_row.get("provider_type", "")
        base_url = (provider_row.get("base_url", "") or "").rstrip("/")
        api_key_env = provider_row.get("api_key_env", "NONE")

    api_key_value = os.environ.get(api_key_env) if api_key_env != "NONE" else None
    cache_key = (provider_type, base_url, api_key_env)
    if not refresh_cache and cache_key in _MODEL_CACHE:
        return sorted(_MODEL_CACHE[cache_key])

    models: List[str] = []

    if provider_type == "openai_compatible":
        # llama.cpp (llama-server), Ollama, vLLM, LM Studio, OpenRouter
        headers = {}
        if api_key_value:
            headers["Authorization"] = f"Bearer {api_key_value}"

        try:
            import requests
        except ImportError:
            console.print(f"{WARN} 'requests' not installed, cannot fetch models")
            return models

        # Normalize base_url for llama.cpp servers
        # Handle both http://localhost:8080 and http://localhost:8080/v1
        if not base_url:
            base_url = "http://localhost:8080"

        # Ensure base_url has /v1 suffix for OpenAI-compatible API
        if not base_url.endswith("/v1"):
            # Don't add /v1 if it already ends with a path that might be an API root
            base_url = f"{base_url}/v1"

        url = f"{base_url}/models"

        timeout = 5.0
        start = time.monotonic()

        try:
            response = requests.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            console.print(f"{WARN} Could not fetch models from {url}: {e}")
            return models

        elapsed = time.monotonic() - start

        if response.status_code == 200:
            try:
                data = response.json()
            except Exception as e:
                console.print(f"{WARN} Failed to parse JSON response: {e}")
                return models

            # Standard OpenAI schema: data[*].id
            if "data" in data and isinstance(data["data"], list):
                models = [item.get("id", "") for item in data["data"] if item.get("id")]
            # llama.cpp /props or native Ollama: models[*].name
            elif "models" in data and isinstance(data["models"], list):
                models = [item.get("name", "") for item in data["models"] if item.get("name")]

            if models:
                console.print(f"{SUCCESS} Discovered {len(models)} models from {url} (elapsed={elapsed:.3f}s)")
            else:
                console.print(f"{WARN} No models found in response from {url}")
        else:
            console.print(f"{WARN} Failed to fetch models: HTTP {response.status_code} from {url}")

    elif provider_type == "openai":
        try:
            import openai
        except ImportError:
            console.print(f"{WARN} 'openai' SDK not installed")
            return models

        try:
            client = openai.OpenAI(api_key=api_key_value)
            response = client.models.list()
            models = [m.id for m in response.data if m.id]
            if models:
                console.print(f"{SUCCESS} Discovered {len(models)} models via OpenAI SDK")
        except Exception as e:
            console.print(f"{WARN} OpenAI SDK error: {e}")

    elif provider_type == "anthropic":
        try:
            import anthropic
        except ImportError:
            console.print(f"{WARN} 'anthropic' SDK not installed")
            return models

        try:
            client = anthropic.Anthropic(api_key=api_key_value)
            response = client.models.list()
            models = [m.id for m in response.data if m.id]
            if models:
                console.print(f"{SUCCESS} Discovered {len(models)} models via Anthropic SDK")
        except Exception as e:
            console.print(f"{WARN} Anthropic SDK error: {e}")

    elif provider_type == "google_genai":
        try:
            import google.generativeai as genai
        except ImportError:
            console.print(f"{WARN} 'google-generativeai' SDK not installed")
            return models

        try:
            genai.configure(api_key=api_key_value)
            response = genai.list_models()
            models = [m.name for m in response if "generateContent" in m.supported_generation_methods]
            if models:
                console.print(f"{SUCCESS} Discovered {len(models)} Gemini models via genai SDK")
        except Exception as e:
            console.print(f"{WARN} genai SDK error: {e}")

    else:
        console.print(f"{WARN} Unknown provider type: {provider_type}")

    models = sorted(set(models))  # deduplicate and sort
    if models:
        _MODEL_CACHE[cache_key] = models
    return models


def resolve_model_name(provider, requested: str | None) -> str | None:
    """The model a Bee or Hive uses when the caller left it blank.

    Order: what was asked for, then the provider's default, then its assistant model, then
    the first detected model - the same order the Web UI shows, so a model that looks chosen
    on screen is the model that gets saved.
    """
    picked = (requested or "").strip()
    if picked:
        return picked
    for value in (provider.default_model, provider.assistant_model):
        if value:
            return value
    models = list(provider.available_models or [])
    return models[0] if models else None


__all__ = ["fetch_provider_models", "resolve_model_name"]