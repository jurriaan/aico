from aico.llm.providers.base import LLMProvider
from aico.llm.providers.openai import OpenAIProvider
from aico.llm.providers.openrouter import OpenRouterProvider

_PROVIDER_MAP = {
    "openrouter/": OpenRouterProvider,
    "openai/": OpenAIProvider,
}


def get_provider_for_model(full_model_string: str) -> tuple[LLMProvider, str, dict[str, str]]:
    """
    Factory that returns the correct Provider strategy, the STRIPPED model name,
    and a dictionary of extra parameters parsed from the model string.
    """
    parts = full_model_string.split("+")
    base_model = parts[0]
    extra_params = {k: v for p in parts[1:] if "=" in p for k, v in [p.split("=", 1)]}

    for prefix, provider_cls in _PROVIDER_MAP.items():
        if base_model.startswith(prefix):
            clean_model_id = base_model[len(prefix) :]
            return provider_cls(), clean_model_id, extra_params

    raise ValueError(
        f"Unrecognized model provider format for '{full_model_string}'. "
        + f"Please use one of ({', '.join(_PROVIDER_MAP.keys())}) followed by <model>, "
        + "or ensure the model is supported."
    )
