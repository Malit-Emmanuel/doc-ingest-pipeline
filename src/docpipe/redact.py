"""Stage 3: redact personal data before anything is stored or embedded.

Personal data should not reach the vector store: embeddings and chunk text are
copied into prompts, logs and caches, where they are hard to delete later. The
detectors target identifiers common in Kenyan documents (in the spirit of the
Data Protection Act, 2019). They are pattern-based, so they reduce risk rather
than guarantee anonymisation; see the README for limits.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass(frozen=True)
class Detector:
    label: str
    pattern: re.Pattern[str]
    validate: Callable[[re.Match[str]], bool] | None = None


DETECTORS: tuple[Detector, ...] = (
    Detector("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # Payment cards: 13-19 digits, optional spaces/dashes, must pass the Luhn check.
    Detector(
        "CARD_NUMBER",
        re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
        lambda m: luhn_valid(re.sub(r"\D", "", m.group())),
    ),
    # Kenyan mobile numbers: +254 / 254 / 0 followed by 7xx or 1xx and six digits.
    Detector("PHONE", re.compile(r"(?<!\d)(?:\+?254|0)[ -]?[17]\d{2}[ -]?\d{3}[ -]?\d{3}(?!\d)")),
    # KRA PIN: letter, nine digits, letter (e.g. A012345678Z).
    Detector("KRA_PIN", re.compile(r"\b[AP]\d{9}[A-Z]\b")),
    # National ID numbers only when labelled, to avoid redacting ordinary numbers.
    Detector(
        "NATIONAL_ID",
        re.compile(r"(?i)\b(?:national\s+)?id(?:\s*(?:no|number|#))?\.?\s*[:\-]?\s*\d{7,8}\b"),
    ),
)


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int]


def redact(text: str) -> RedactionResult:
    counts: Counter[str] = Counter()
    for det in DETECTORS:

        def _sub(m: re.Match[str], det: Detector = det) -> str:
            if det.validate and not det.validate(m):
                return m.group()
            counts[det.label] += 1
            return f"[{det.label}]"

        text = det.pattern.sub(_sub, text)
    return RedactionResult(text=text, counts=dict(counts))


def find_pii(text: str) -> dict[str, int]:
    """Count what the detectors would still find (used as a post-redaction quality check)."""
    return redact(text).counts
