import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


def _get_env_var_or_fail(var_name: str, provider_display_name: str) -> str:
    val = os.getenv(var_name)
    if not val:
        raise ValueError(f"{provider_display_name} requires the environment variable '{var_name}' to be set.")
    return val


def resolve_provider_config(model_input: str) -> tuple[str, str | None, str, bool]:
    """
    Resolves (api_key, base_url, actual_model_name, is_openrouter) based on prefix.
    """
    if model_input.startswith("openrouter/"):
        actual_model = model_input[len("openrouter/") :]
        api_key = _get_env_var_or_fail("OPENROUTER_API_KEY", "OpenRouter")
        base_url = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
        return api_key, base_url, actual_model, True

    if model_input.startswith("openai/"):
        actual_model = model_input[len("openai/") :]
        api_key = _get_env_var_or_fail("OPENAI_API_KEY", "OpenAI")
        base_url = os.getenv("OPENAI_BASE_URL")  # Use client default if None
        return api_key, base_url, actual_model, False

    # No implicit fallback to OpenAI; an explicit prefix (openai/ or openrouter/) or a model name
    # that matches a known provider's format should be used.
    # Otherwise, it's an unrecognized model provider setup.
    raise ValueError(
        f"Unrecognized model provider format for '{model_input}'. "
        + "Please use 'openrouter/<model>' or 'openai/<model>', or ensure the model is supported."
    )


def create_client(model_input: str) -> tuple["OpenAI", str, dict[str, object]]:
    """
    Factory to create an OpenAI client based on the model string.

    Returns:
        - client: Instantiated OpenAI client.
        - actual_model: The model name stripped of routing prefixes.
        - extra_kwargs: Dictionary containing provider-specific params (e.g. extra_body).
    """
    api_key, base_url, actual_model, is_openrouter = resolve_provider_config(model_input)

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    extra_kwargs: dict[str, object] = {}

    if is_openrouter:
        # OpenRouter requires this to return usage statistics including reasoning/cache
        extra_kwargs["extra_body"] = {
            "usage": {"include": True},
        }

    return client, actual_model, extra_kwargs
