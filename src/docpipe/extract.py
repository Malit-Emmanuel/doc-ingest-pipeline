"""Stage 1: extract raw text from source files, page by page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


class UnsupportedFileType(ValueError):
    pass


class ExtractionError(RuntimeError):
    pass


@dataclass
class ExtractedDocument:
    path: Path
    source_type: str
    pages: list[str]
    title: str

    @property
    def page_count(self) -> int:
        return len(self.pages)


def discover(root: Path) -> list[Path]:
    """All files under root (or root itself), sorted for deterministic runs. Hidden files skipped."""
    if root.is_file():
        return [root]
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def extract(path: Path) -> ExtractedDocument:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileType(f"unsupported file type: {suffix or '(none)'}")
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            meta_title = (reader.metadata.title if reader.metadata else None) or ""
            return ExtractedDocument(path, "pdf", pages, meta_title.strip() or path.stem)
        if suffix == ".docx":
            doc = DocxDocument(str(path))
            text = "\n\n".join(p.text for p in doc.paragraphs)
            title = (doc.core_properties.title or "").strip() or path.stem
            return ExtractedDocument(path, "docx", [text], title)
        text = path.read_text(encoding="utf-8", errors="replace")
        return ExtractedDocument(path, suffix.lstrip("."), [text], _first_heading(text) or path.stem)
    except UnsupportedFileType:
        raise
    except Exception as exc:  # corrupt or encrypted files end up in quarantine, not a crash
        raise ExtractionError(f"{type(exc).__name__}: {exc}") from exc


def _first_heading(text: str) -> str | None:
    """A Markdown heading, or a short first line, used as the document title."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or None
        if line:
            return line if len(line) <= 100 else None
    return None
