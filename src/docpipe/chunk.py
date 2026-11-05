"""Stage 4: split documents into overlapping chunks sized for retrieval.

Sizes are counted in words, a close and dependency-free approximation of tokens
for English text. Paragraph and sentence boundaries are respected where possible
so a chunk rarely starts or ends mid-sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[\"'(])")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    word_count: int


def _units(text: str, max_words: int) -> list[list[str]]:
    """Paragraphs, split into sentences when too long, split into word windows as a last resort."""
    units: list[list[str]] = []
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        words = para.split()
        if len(words) <= max_words:
            units.append(words)
            continue
        for sentence in _SENTENCE_END.split(para):
            s_words = sentence.split()
            for start in range(0, len(s_words), max_words):
                piece = s_words[start : start + max_words]
                if piece:
                    units.append(piece)
    return units


def chunk_text(text: str, size: int = 200, overlap: int = 40) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and smaller than size")
    chunks: list[Chunk] = []
    current: list[str] = []

    def emit() -> None:
        if current:
            chunks.append(Chunk(len(chunks), " ".join(current), len(current)))

    for unit in _units(text, size):
        if current and len(current) + len(unit) > size:
            emit()
            current = current[-overlap:] if overlap else []
            # keep the overlap only while it leaves room for the next unit
            while current and len(current) + len(unit) > size:
                current = current[1:]
        current = current + unit
    emit()
    return chunks
