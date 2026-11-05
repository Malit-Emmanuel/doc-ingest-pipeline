"""Stage 2: normalise extracted text so chunks and embeddings are consistent."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_PAGE_NUMBER = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)


def remove_repeated_lines(pages: list[str], min_pages: int = 3, share: float = 0.6) -> list[str]:
    """Drop running headers/footers: short lines that repeat on most pages of a long document."""
    if len(pages) < min_pages:
        return pages
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({line.strip() for line in page.splitlines() if line.strip()})
    repeated = {line for line, n in counts.items() if n / len(pages) >= share and len(line) <= 80}
    return ["\n".join(line for line in page.splitlines() if line.strip() not in repeated) for page in pages]


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if not _PAGE_NUMBER.match(line)]
    text = "\n".join(lines)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def clean_pages(pages: list[str]) -> str:
    """Clean every page and join them into one document text."""
    pages = remove_repeated_lines(pages)
    return "\n\n".join(c for c in (clean_text(p) for p in pages) if c)
