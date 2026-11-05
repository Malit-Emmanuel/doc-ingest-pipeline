"""Configuration loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

EMBEDDING_DIM = 384


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://docpipe:docpipe@localhost:5432/docpipe"
    vector_backend: str = "auto"  # auto | pgvector | array
    embedder: str = "hashing"  # hashing | sentence-transformers
    chunk_size: int = 200
    chunk_overlap: int = 40
    min_doc_chars: int = 50
    min_chars_per_pdf_page: int = 20
    retention_days: int = 365

    def __post_init__(self) -> None:
        if self.vector_backend not in {"auto", "pgvector", "array"}:
            raise ValueError(f"VECTOR_BACKEND must be auto, pgvector or array, got {self.vector_backend!r}")
        if self.embedder not in {"hashing", "sentence-transformers"}:
            raise ValueError(f"EMBEDDER must be hashing or sentence-transformers, got {self.embedder!r}")
        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE must be positive")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be >= 0 and smaller than CHUNK_SIZE")
        if self.retention_days <= 0:
            raise ValueError("RETENTION_DAYS must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        return cls(
            database_url=os.getenv("DATABASE_URL", d.database_url),
            vector_backend=os.getenv("VECTOR_BACKEND", d.vector_backend),
            embedder=os.getenv("EMBEDDER", d.embedder),
            chunk_size=int(os.getenv("CHUNK_SIZE", d.chunk_size)),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", d.chunk_overlap)),
            min_doc_chars=int(os.getenv("MIN_DOC_CHARS", d.min_doc_chars)),
            min_chars_per_pdf_page=int(os.getenv("MIN_CHARS_PER_PDF_PAGE", d.min_chars_per_pdf_page)),
            retention_days=int(os.getenv("RETENTION_DAYS", d.retention_days)),
        )

    def public_dict(self) -> dict:
        """Settings safe to record in the run log (credentials removed)."""
        data = asdict(self)
        data.pop("database_url")
        return data
