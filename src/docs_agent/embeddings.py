"""Text embeddings. The default runs locally with fastembed (ONNX), so no API key is needed."""

import asyncio
from typing import Protocol


class Embedder(Protocol):
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local CPU embeddings. The model is loaded on first use and reused afterwards."""

    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().embed(texts)]

    def _embed_query(self, text: str) -> list[float]:
        return next(iter(self._load().query_embed(text))).tolist()

    # Inference is CPU-bound, so it runs in a worker thread to keep the event loop free.
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_documents, texts)

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_query, text)
