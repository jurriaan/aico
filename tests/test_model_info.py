# pyright: standard

from pathlib import Path

from pytest_mock import MockerFixture

from aico.lib.model_info import (
    CACHE_FILENAME,
    ModelRegistry,
    _load_cache,
    _update_registry,
    get_model_info,
)
from aico.lib.models import ModelInfo


def test_update_registry_merges_priority(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN mocked fetch functions returning conflicting data
    mock_cache_path = tmp_path / "models.json"
    _ = mocker.patch(
        "aico.lib.model_info.get_cache_path",
        return_value=mock_cache_path,
    )
    _ = mocker.patch(
        "aico.lib.model_info._fetch_and_normalize_litellm",
        return_value={
            "gpt-4": ModelInfo(input_cost_per_token=1.0),
            "legacy-model": ModelInfo(input_cost_per_token=0.5),
        },
    )
    _ = mocker.patch(
        "aico.lib.model_info._fetch_and_normalize_openrouter",
        return_value={
            "gpt-4": ModelInfo(input_cost_per_token=2.0),  # OpenRouter overwrites
            "google/gemini": ModelInfo(input_cost_per_token=0.1),
        },
    )

    # WHEN _update_registry is called
    registry: ModelRegistry | None = _update_registry(mock_cache_path)

    # THEN registry is created successfully
    assert registry is not None
    models = registry["models"]

    # AND OpenRouter data overwrites LiteLLM for conflicts
    assert models["gpt-4"].input_cost_per_token == 2.0
    # AND all unique models are present
    assert "legacy-model" in models
    assert "google/gemini" in models
    # AND cache is persisted
    assert mock_cache_path.is_file()


def test_get_model_info_lookup_strategies(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a fake registry with specific lookup keys
    fake_registry: ModelRegistry = {
        "last_fetched": "2023-01-01T00:00:00",
        "models": {
            "gpt-4o": ModelInfo(max_input_tokens=100),  # Exact match
            "google/gemini-pro": ModelInfo(max_input_tokens=200),  # Prefix strip
            "claude-3-opus": ModelInfo(max_input_tokens=300),  # Vendor strip
        },
    }
    _ = mocker.patch("aico.lib.model_info.get_cache_path")
    _ = mocker.patch("aico.lib.model_info._ensure_cache", return_value=fake_registry)

    # WHEN get_model_info is called with various model IDs
    exact_match = get_model_info("gpt-4o")
    prefix_strip = get_model_info("openrouter/google/gemini-pro")
    vendor_strip = get_model_info("anthropic/claude-3-opus")
    unknown = get_model_info("unknown/model")

    # THEN exact match returns correct info
    assert exact_match.max_input_tokens == 100
    # AND prefix stripping works
    assert prefix_strip.max_input_tokens == 200
    # AND vendor stripping works
    assert vendor_strip.max_input_tokens == 300
    # AND unknown models return empty ModelInfo
    assert unknown.max_input_tokens is None


def test_load_cache_handles_corruption(tmp_path: Path) -> None:
    # GIVEN a corrupt cache file
    cache_file = tmp_path / CACHE_FILENAME
    _ = cache_file.write_text("invalid json {")

    # WHEN _load_cache is called
    result = _load_cache(cache_file)

    # THEN returns None without crashing
    assert result is None
