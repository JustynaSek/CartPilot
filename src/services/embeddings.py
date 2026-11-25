"""Product-name embedding generator (`gemini-embedding-001`, 768 dimensions).

Can be disabled via `EMBEDDINGS_ENABLED=false` (e.g. in automated tests or offline dev)
so no external API calls are made.
"""

from collections.abc import Sequence

from google import genai
from google.genai import types

from src.core.config import Settings, get_settings


class EmbeddingService:
    """Async embedding provider returning 768-dim vectors for `pgvector`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self._settings.embeddings_enabled

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float] | None]:
        """Return one embedding vector per input string, or `[None, ...]` when disabled."""
        if not texts:
            return []
        if not self.enabled:
            return [None] * len(texts)

        api_key = (
            self._settings.gemini_api_key.get_secret_value()
            if self._settings.gemini_api_key is not None
            else None
        )
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.embed_content(
            model=self._settings.model_embedding,
            contents=list(texts),
            config=types.EmbedContentConfig(
                output_dimensionality=self._settings.embedding_dimensions
            ),
        )
        embeddings = response.embeddings or []
        return [list(emb.values) if emb.values is not None else None for emb in embeddings]
