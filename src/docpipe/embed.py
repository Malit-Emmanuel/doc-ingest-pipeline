"""Stage 5: turn chunk text into vectors.

Two interchangeable embedders share one interface:

* HashingEmbedder  - deterministic feature hashing of words and word pairs. No
  model download, so tests and CI run offline and results are reproducible.
* SentenceTransformerEmbedder - all-MiniLM-L6-v2, a real semantic model with the
  same 384 dimensions, so switching needs no schema change.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from .config import EMBEDDING_DIM

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def _index_and_sign(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        return h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            words = _WORD.findall(text.lower())
            features = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
            for feat in features:
                idx, sign = self._index_and_sign(feat)
                out[row, idx] += sign
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out


class SentenceTransformerEmbedder:
    name = "all-MiniLM-L6-v2"
    dim = EMBEDDING_DIM

    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError('install the model extra: pip install ".[models]"') from exc
        self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - needs model download
        vecs = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return vecs.astype(np.float32)


def get_embedder(name: str) -> Embedder:
    if name == "hashing":
        return HashingEmbedder()
    if name == "sentence-transformers":
        return SentenceTransformerEmbedder()
    raise ValueError(f"unknown embedder: {name}")
