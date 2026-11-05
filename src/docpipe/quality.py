"""Stage 6: data-quality checks run on every document before it is loaded.

Each check returns a CheckResult. A failed *blocking* check sends the document
to quarantine; non-blocking failures are recorded but the document still loads.
Every result is written to the quality_results table, so data quality can be
reported on per run, per document and per check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .chunk import Chunk
from .redact import find_pii


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    blocking: bool
    detail: dict = field(default_factory=dict)


def check_document(
    *,
    text: str,
    source_type: str,
    page_count: int,
    chunks: list[Chunk],
    embeddings: np.ndarray | None,
    expected_dim: int,
    max_chunk_words: int,
    min_doc_chars: int,
    min_chars_per_pdf_page: int,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            "min_text_length",
            len(text) >= min_doc_chars,
            True,
            {"chars": len(text), "min": min_doc_chars},
        )
    )

    if source_type == "pdf":
        per_page = len(text) / max(page_count, 1)
        # Very little text per page usually means a scanned PDF that needs OCR.
        results.append(
            CheckResult(
                "pdf_text_density",
                per_page >= min_chars_per_pdf_page,
                True,
                {"chars_per_page": round(per_page, 1), "min": min_chars_per_pdf_page},
            )
        )

    results.append(CheckResult("has_chunks", len(chunks) > 0, True, {"chunks": len(chunks)}))

    oversized = [c.index for c in chunks if c.word_count > max_chunk_words]
    results.append(
        CheckResult(
            "chunk_size_bounds",
            not oversized,
            True,
            {"oversized_chunks": oversized, "max_words": max_chunk_words},
        )
    )

    residue = find_pii(text)
    results.append(CheckResult("no_pii_residue", not residue, True, {"found": residue}))

    if chunks:
        distinct = len({c.text for c in chunks})
        dup_ratio = 1 - distinct / len(chunks)
        results.append(
            CheckResult(
                "duplicate_chunk_ratio",
                dup_ratio <= 0.5,
                False,
                {"ratio": round(dup_ratio, 3)},
            )
        )

    if embeddings is not None:
        shape_ok = embeddings.shape == (len(chunks), expected_dim)
        finite_ok = bool(np.isfinite(embeddings).all())
        norms = np.linalg.norm(embeddings, axis=1) if embeddings.size else np.array([])
        zero_rows = [int(i) for i in np.where(norms == 0)[0]]
        results.append(
            CheckResult(
                "embedding_integrity",
                shape_ok and finite_ok and not zero_rows,
                True,
                {
                    "shape": list(embeddings.shape),
                    "expected": [len(chunks), expected_dim],
                    "finite": finite_ok,
                    "zero_vectors": zero_rows,
                },
            )
        )

    return results


def blocking_failures(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.blocking and not r.passed]
