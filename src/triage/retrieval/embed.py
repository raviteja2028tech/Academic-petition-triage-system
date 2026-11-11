"""Local embeddings (sentence-transformers). No paid API. The model is cached under HF_HOME so it is
downloaded once, not on every ingestion run."""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Optional, Protocol

from .chunk import CHUNKER_VERSION


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    @property
    def tag(self) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, cache_dir: Optional[str] = None):
        if not model_name:
            raise EmbeddingError("EMBED_MODEL is not set. Set it in your .env (see .env.example).")
        self.model_name = model_name
        self.cache_dir = cache_dir or None
        self._model = None

    def _load(self):
        if self._model is None:
            if self.cache_dir:
                os.environ.setdefault("HF_HOME", self.cache_dir)
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, cache_folder=self.cache_dir, device="cpu")
            except MemoryError as e:
                raise EmbeddingError("not enough memory to load the embedding model") from e
            except Exception as e:  # noqa: BLE001  (offline, unknown model, corrupted cache ...)
                raise EmbeddingError(f"cannot load embedding model '{self.model_name}': {type(e).__name__}: {e}. "
                                     "Check the model name and network access for the first download, "
                                     "or pre-populate the HF cache volume.") from e
        return self._model

    @property
    def tag(self) -> str:
        m = self._load()
        dim = m.get_sentence_embedding_dimension()
        return f"st|{self.model_name}|dim{dim}|norm|{CHUNKER_VERSION}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            v = self._load().encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        except EmbeddingError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EmbeddingError(f"embedding failed: {type(e).__name__}: {e}") from e
        return v.tolist()


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder. TEST FIXTURE ONLY - not a semantic model."""

    def __init__(self, dim: int = 128, name: str = "hash"):
        self.dim, self.name = dim, name

    @property
    def tag(self) -> str:
        return f"fake|{self.name}|dim{self.dim}|{CHUNKER_VERSION}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out
