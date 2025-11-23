from aico.core.providers.base import LLMProvider
from aico.core.providers.openai import OpenAIProvider
from aico.core.providers.openrouter import OpenRouterProvider


def get_provider_for_model(full_model_string: str) -> tuple[LLMProvider, str]:
    """
    Factory that returns the correct Provider strategy and the STRIPPED model name.
    """
    if full_model_string.startswith("openrouter/"):
        # Router handles the routing logic. It hands the Provider the clean ID.
        clean_model_id = full_model_string[len("openrouter/") :]
        return OpenRouterProvider(), clean_model_id

    if full_model_string.startswith("openai/"):
        clean_model_id = full_model_string[len("openai/") :]
        return OpenAIProvider(), clean_model_id

    raise ValueError(
        f"Unrecognized model provider format for '{full_model_string}'. "
        + "Please use 'openrouter/<model>' or 'openai/<model>', or ensure the model is supported."
    )
