import os
from unittest import mock

import pytest
from openai import OpenAI

from aico.core.provider_router import create_client, resolve_provider_config


def test_resolve_openrouter_defaults() -> None:
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}, clear=True):
        api_key, base_url, model, is_or = resolve_provider_config("openrouter/google/gemini-flash")
        assert api_key == "sk-or-test"
        assert base_url == "https://openrouter.ai/api/v1"
        assert model == "google/gemini-flash"
        assert is_or is True


def test_resolve_openrouter_override_base() -> None:
    with mock.patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_API_BASE": "https://custom.or/v1"},
        clear=True,
    ):
        _, base_url, _, _ = resolve_provider_config("openrouter/foo")
        assert base_url == "https://custom.or/v1"


def test_resolve_openai_prefix() -> None:
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-oa-test"}, clear=True):
        api_key, base_url, model, is_or = resolve_provider_config("openai/gpt-4o")
        assert api_key == "sk-oa-test"
        assert base_url is None  # Defaults to library default
        assert model == "gpt-4o"
        assert is_or is False


def test_resolve_openai_implicit_fails() -> None:
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-oa-test"}, clear=True):
        with pytest.raises(ValueError) as excinfo:
            _ = resolve_provider_config("gpt-4o")
        assert (
            "Unrecognized model provider format for 'gpt-4o'. Please use 'openrouter/<model>' or 'openai/<model>', "
            + "or ensure the model is supported."
            in str(excinfo.value)
        )


def test_resolve_openai_override_base() -> None:
    with mock.patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "sk-oa-test", "OPENAI_BASE_URL": "http://localhost:11434/v1"},
        clear=True,
    ):
        _, base_url, _, _ = resolve_provider_config("openai/gpt-4o")
        assert base_url == "http://localhost:11434/v1"


def test_missing_key_exits() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError) as excinfo:
            _ = resolve_provider_config("openrouter/foo")
        assert "OpenRouter requires the environment variable 'OPENROUTER_API_KEY' to be set." in str(excinfo.value)


def test_create_client_openrouter() -> None:
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}, clear=True):
        client, model, kwargs = create_client("openrouter/anthropic/claude-3")

        assert isinstance(client, OpenAI)
        assert client.api_key == "sk-or-test"
        assert str(client.base_url) == "https://openrouter.ai/api/v1/"
        assert model == "anthropic/claude-3"
        assert kwargs.get("extra_body") == {"usage": {"include": True}}


def test_create_client_openai() -> None:
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-oa-test"}, clear=True):
        client, model, kwargs = create_client("openai/gpt-4o")

        assert isinstance(client, OpenAI)
        assert client.api_key == "sk-oa-test"
        # OpenAI client default base_url is https://api.openai.com/v1/
        assert str(client.base_url) == "https://api.openai.com/v1/"
        assert model == "gpt-4o"
        assert "extra_body" not in kwargs
