"""Centralized, provider-agnostic LLM model registry.

Reads model identifiers from `Settings` (`MODEL_FAST`, `MODEL_REASONING`, `MODEL_EMBEDDING`)
so no agent module ever hardcodes a model name or provider.
"""

from typing import Literal

from pydantic_ai.models import Model

from src.core.config import Settings, get_settings

ModelRef = Model | str
ModelTier = Literal["fast", "reasoning"]


def get_fast_model(settings: Settings | None = None) -> str:
    """Return the configured fast/multimodal model string (e.g. `google-gla:gemini-3.8-flash`)."""
    return (settings or get_settings()).model_fast


def get_reasoning_model(settings: Settings | None = None) -> str:
    """Return the configured reasoning model string (e.g. `google-gla:gemini-4-hydrogen`)."""
    return (settings or get_settings()).model_reasoning


def get_embedding_model(settings: Settings | None = None) -> str:
    """Return the configured embedding model name (e.g. `gemini-embedding-001`)."""
    return (settings or get_settings()).model_embedding


def resolve_model(
    override: ModelRef | None = None,
    *,
    tier: ModelTier = "fast",
    settings: Settings | None = None,
) -> ModelRef:
    """Resolve an explicit model override (e.g. `TestModel` in tests) or fall back to config."""
    if override is not None:
        return override
    if tier == "reasoning":
        return get_reasoning_model(settings)
    return get_fast_model(settings)
