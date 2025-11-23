import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, TypedDict

from pydantic import TypeAdapter, ValidationError, WrapValidator

from aico.lib.atomic_io import atomic_write_text
from aico.lib.models import ModelInfo

# URL for the litellm model cost map
LITELLM_MODEL_COST_MAP_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

CACHE_TTL_DAYS = 14
CACHE_FILENAME = "models.json"


class ModelRegistry(TypedDict):
    last_fetched: str
    models: dict[str, ModelInfo]


# --- Private Models for External API Parsing ---
class _OpenRouterPricing(TypedDict):
    prompt: str
    completion: str


class _OpenRouterItem(TypedDict):
    id: str
    context_length: int
    pricing: _OpenRouterPricing


class _OpenRouterResponse(TypedDict):
    data: list[_OpenRouterItem]


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
    except (httpx.HTTPError, OSError):
        # Fail silently on network/parsing errors to maintain offline flow
        return None


def _fetch_openrouter_data() -> bytes | None:
    import httpx

    try:
        # Use a short timeout to avoid blocking user workflow
        response = httpx.get(OPENROUTER_MODELS_URL, timeout=3.0, follow_redirects=True)
        _ = response.raise_for_status()
        return response.content
    except (httpx.HTTPError, OSError):
        # Fail silently on network/parsing errors to maintain offline flow
        return None


def _load_cache(cache_file: Path) -> ModelRegistry | None:
    if not cache_file.is_file():
        return None

    try:
        content = cache_file.read_text(encoding="utf-8")
        return TypeAdapter(ModelRegistry).validate_json(content)
    except (ValidationError, OSError):
        return None


def _fetch_and_normalize_litellm() -> dict[str, ModelInfo] | None:
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
    return parsed_models if parsed_models else None


def _fetch_and_normalize_openrouter() -> dict[str, ModelInfo] | None:
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

    for item in response["data"]:
        try:
            # OpenRouter sends pricing as strings, explicit float conversion
            p_cost = float(item["pricing"]["prompt"])
            c_cost = float(item["pricing"]["completion"])
        except ValueError:
            p_cost = None
            c_cost = None

        parsed_models[item["id"]] = ModelInfo(
            max_input_tokens=item["context_length"],
            input_cost_per_token=p_cost,
            output_cost_per_token=c_cost,
        )

    return parsed_models if parsed_models else None


def _update_registry(cache_file: Path) -> ModelRegistry | None:
    # 1. Fetch Fallback (LiteLLM)
    models = _fetch_and_normalize_litellm() or {}

    # 2. Fetch Primary (OpenRouter) - Overwrites overlap
    if or_data := _fetch_and_normalize_openrouter():
        models.update(or_data)

    if not models:
        return None

    registry = ModelRegistry(last_fetched=datetime.now(UTC).isoformat(), models=models)

    try:
        atomic_write_text(cache_file, TypeAdapter(ModelRegistry).dump_json(registry))
        return registry
    except OSError:
        return None


def _ensure_cache(cache_file: Path) -> ModelRegistry | None:
    cache = _load_cache(cache_file)

    should_fetch = False
    if cache is None:
        should_fetch = True
    else:
        try:
            last_fetched = datetime.fromisoformat(cache["last_fetched"])
            if datetime.now(UTC) - last_fetched > timedelta(days=CACHE_TTL_DAYS):
                should_fetch = True
        except ValueError:
            should_fetch = True

    if should_fetch:
        new_cache = _update_registry(cache_file)
        if new_cache:
            return new_cache

    return cache


def get_model_info(model_id: str) -> ModelInfo:
    cache_file = get_cache_path(CACHE_FILENAME)
    registry = _ensure_cache(cache_file)

    if not registry:
        return ModelInfo()

    models = registry["models"]

    # 1. Exact Match
    if model_id in models:
        return models[model_id]

    # 2. Strip Prefix (e.g., 'openai/gpt-4o' -> 'gpt-4o', 'openrouter/google/gemini' -> 'google/gemini')
    if "/" in model_id:
        stripped = model_id.split("/", 1)[1]
        if stripped in models:
            return models[stripped]

    # 3. Strip Vendor (e.g. 'google/gemini' -> 'gemini') - mostly for LiteLLM format
    bare_name = model_id.split("/")[-1]
    if bare_name in models:
        return models[bare_name]

    return ModelInfo()
