import os
from unittest import mock

import pytest
from openai import OpenAI

from aico.llm.providers.openai import OpenAIProvider
from aico.llm.providers.openrouter import OpenRouterProvider
from aico.llm.router import get_provider_for_model


def test_get_provider_for_model_openai():
    provider, clean_model, extra_params = get_provider_for_model("openai/gpt-4o")
    assert isinstance(provider, OpenAIProvider)
    assert clean_model == "gpt-4o"
    assert extra_params == {}


def test_get_provider_for_model_openrouter():
    provider, clean_model, extra_params = get_provider_for_model("openrouter/anthropic/claude-3.5-sonnet")
    assert isinstance(provider, OpenRouterProvider)
    assert clean_model == "anthropic/claude-3.5-sonnet"
    assert extra_params == {}


def test_get_provider_for_model_with_params():
    provider, clean_model, extra_params = get_provider_for_model("openai/o1+reasoning_effort=high")
    assert isinstance(provider, OpenAIProvider)
    assert clean_model == "o1"
    assert extra_params == {"reasoning_effort": "high"}


def test_get_provider_for_model_with_multiple_params():
    _, clean_model, extra_params = get_provider_for_model("openrouter/meta/llama+ext=val+effort=low")
    assert clean_model == "meta/llama"
    assert extra_params == {"ext": "val", "effort": "low"}


def test_get_provider_for_model_invalid_prefix():
    with pytest.raises(ValueError, match="Unrecognized model provider format"):
        _ = get_provider_for_model("invalid/model")


def test_openai_provider_configure_request():
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        provider = OpenAIProvider()
        config = provider.configure_request("gpt-4o", {})
        assert isinstance(config.client, OpenAI)
        assert config.client.api_key == "sk-test"
        assert config.model_id == "gpt-4o"
        assert config.extra_kwargs == {}


def test_openai_provider_configure_request_with_reasoning_effort():
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        provider = OpenAIProvider()
        config = provider.configure_request("o1", {"reasoning_effort": "medium"})
        assert config.extra_kwargs == {"reasoning_effort": "medium"}


def test_openrouter_provider_configure_request():
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
        provider = OpenRouterProvider()
        config = provider.configure_request("anthropic/claude-3.5-sonnet", {})
        assert isinstance(config.client, OpenAI)
        assert config.client.api_key == "sk-or-test"
        assert str(config.client.base_url) == "https://openrouter.ai/api/v1/"
        assert config.model_id == "anthropic/claude-3.5-sonnet"
        assert config.extra_kwargs == {"extra_body": {"usage": {"include": True}}}


def test_openrouter_provider_configure_request_with_reasoning_effort():
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
        provider = OpenRouterProvider()
        config = provider.configure_request("o1", {"reasoning_effort": "high"})
        assert config.extra_kwargs == {
            "extra_body": {
                "usage": {"include": True},
                "reasoning": {"effort": "high"},
            }
        }
