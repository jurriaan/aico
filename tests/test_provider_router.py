import os
from unittest import mock

import pytest
from openai import OpenAI

from aico.core.provider_router import get_provider_for_model
from aico.core.providers.openai import OpenAIProvider
from aico.core.providers.openrouter import OpenRouterProvider


def test_get_provider_for_model_openai():
    provider, clean_model = get_provider_for_model("openai/gpt-4o")
    assert isinstance(provider, OpenAIProvider)
    assert clean_model == "gpt-4o"


def test_get_provider_for_model_openrouter():
    provider, clean_model = get_provider_for_model("openrouter/anthropic/claude-3.5-sonnet")
    assert isinstance(provider, OpenRouterProvider)
    assert clean_model == "anthropic/claude-3.5-sonnet"


def test_get_provider_for_model_invalid_prefix():
    with pytest.raises(ValueError, match="Unrecognized model provider format"):
        _ = get_provider_for_model("invalid/model")


def test_openai_provider_configure_request():
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        provider = OpenAIProvider()
        client, model_id, kwargs = provider.configure_request("gpt-4o")
        assert isinstance(client, OpenAI)
        assert client.api_key == "sk-test"
        assert model_id == "gpt-4o"
        assert kwargs == {}


def test_openrouter_provider_configure_request():
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
        provider = OpenRouterProvider()
        client, model_id, kwargs = provider.configure_request("anthropic/claude-3.5-sonnet")
        assert isinstance(client, OpenAI)
        assert client.api_key == "sk-or-test"
        assert str(client.base_url) == "https://openrouter.ai/api/v1/"
        assert model_id == "anthropic/claude-3.5-sonnet"
        assert kwargs == {"extra_body": {"usage": {"include": True}}}
