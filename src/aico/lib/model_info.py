import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, WrapValidator
from pydantic.dataclasses import dataclass

from aico.lib.atomic_io import atomic_write_text
from aico.lib.models import ModelInfo

# URL for the litellm model cost map
LITELLM_MODEL_COST_MAP_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

CACHE_TTL_DAYS = 14
LITELLM_CACHE_FILENAME = "model_info.json"
OPENROUTER_CACHE_FILENAME = "model_info_openrouter.json"


class ModelCache(BaseModel):
    last_fetched: str
    models: dict[str, ModelInfo]


# --- Private Models for External API Parsing ---


@dataclass(frozen=True, slots=True)
class _OpenRouterPricing:
    prompt: str = "0"
    completion: str = "0"


@dataclass(frozen=True, slots=True)
class _OpenRouterItem:
    id: str
    # OpenRouter sends context_length as an integer
    context_length: int = Field(default=0)
    pricing: _OpenRouterPricing = Field(default_factory=_OpenRouterPricing)


@dataclass(frozen=True, slots=True)
class _OpenRouterResponse:
    data: list[_OpenRouterItem] = Field(default_factory=list)


def get_cache_path(filename: str) -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    cache_dir = Path(xdg_cache) / "aico" if xdg_cache else Path.home() / ".cache" / "aico"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename


def _fetch_litellm_data() -> bytes | None:
    import httpx

    try:
        # Use a short timeout to avoid blocking user workflow
        response = httpx.get(LITELLM_MODEL_COST_MAP_URL, timeout=3.0, follow_redirects=True)
        _ = response.raise_for_status()
        return response.content
    except (httpx.HTTPError, json.JSONDecodeError, OSError):
        # Fail silently on network/parsing errors to maintain offline flow
        return None


def _fetch_openrouter_data() -> bytes | None:
    import httpx

    try:
        # Use a short timeout to avoid blocking user workflow
        response = httpx.get(OPENROUTER_MODELS_URL, timeout=3.0, follow_redirects=True)
        _ = response.raise_for_status()
        return response.content
    except (httpx.HTTPError, json.JSONDecodeError, OSError):
        # Fail silently on network/parsing errors to maintain offline flow
        return None


def _load_cache(cache_file: Path) -> ModelCache | None:
    if not cache_file.is_file():
        return None

    try:
        content = cache_file.read_text(encoding="utf-8")
        return ModelCache.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError, OSError):
        return None


def _update_litellm_cache(cache_file: Path) -> ModelCache | None:
    raw_data = _fetch_litellm_data()
    if not raw_data:
        return None

    def invalid_to_none(v: Any, handler: Callable[[Any], Any]) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
        try:
            return handler(v)  # pyright: ignore[reportAny]
        except ValidationError:
            return None

    type_adapter = TypeAdapter(dict[str, Annotated[ModelInfo | None, WrapValidator(invalid_to_none)]])

    parsed_models: dict[str, ModelInfo] = {
        k: v for k, v in type_adapter.validate_json(raw_data).items() if v is not None
    }
    cache = ModelCache(last_fetched=datetime.now(UTC).isoformat(), models=parsed_models)

    try:
        atomic_write_text(cache_file, cache.model_dump_json())
        return cache
    except OSError:
        return None


def _update_openrouter_cache(cache_file: Path) -> ModelCache | None:
    raw_data = _fetch_openrouter_data()
    if not raw_data:
        return None

    try:
        # Parse with strict schema validation using TypeAdapter[dataclass]
        # This gives us runtime validation of the external API structure.
        response = TypeAdapter(_OpenRouterResponse).validate_json(raw_data)
    except ValidationError:
        return None

    parsed_models: dict[str, ModelInfo] = {}

    for item in response.data:
        try:
            # OpenRouter sends pricing as strings, explicit float conversion
            p_cost = float(item.pricing.prompt)
            c_cost = float(item.pricing.completion)
        except ValueError:
            p_cost = None
            c_cost = None

        parsed_models[item.id] = ModelInfo(
            max_input_tokens=item.context_length,
            input_cost_per_token=p_cost,
            output_cost_per_token=c_cost,
        )

    cache = ModelCache(last_fetched=datetime.now(UTC).isoformat(), models=parsed_models)

    try:
        atomic_write_text(cache_file, cache.model_dump_json())
        return cache
    except OSError:
        return None


def _ensure_specific_cache(filename: str, update_func: Callable[[Path], ModelCache | None]) -> ModelCache | None:
    cache_file = get_cache_path(filename)
    cache = _load_cache(cache_file)

    should_fetch = False
    if cache is None:
        should_fetch = True
    else:
        try:
            last_fetched = datetime.fromisoformat(cache.last_fetched)
            if datetime.now(UTC) - last_fetched > timedelta(days=CACHE_TTL_DAYS):
                should_fetch = True
        except ValueError:
            should_fetch = True

    if should_fetch:
        new_cache = update_func(cache_file)
        if new_cache:
            return new_cache

    return cache


def get_model_info(model_id: str) -> ModelInfo:
    # 1. Check OpenRouter cache first (Primary)
    or_cache = _ensure_specific_cache(OPENROUTER_CACHE_FILENAME, _update_openrouter_cache)

    if or_cache:
        or_map = or_cache.models

        # OpenRouter IDs usually look like "provider/model" (e.g. "google/gemini-pro")
        # Our `model_id` might be "openrouter/google/gemini-pro"
        lookup_key = model_id
        if lookup_key.startswith("openrouter/"):
            lookup_key = lookup_key[len("openrouter/") :]

        if lookup_key in or_map:
            return or_map[lookup_key]

    # 2. Check LiteLLM cache (Fallback)
    llm_cache = _ensure_specific_cache(LITELLM_CACHE_FILENAME, _update_litellm_cache)
    llm_map = llm_cache.models if llm_cache else {}

    if model_id in llm_map:
        return llm_map[model_id]

    bare_model = model_id.split("/")[-1]
    if bare_model in llm_map:
        return llm_map[bare_model]

    # Return empty info if not found
    return ModelInfo()
