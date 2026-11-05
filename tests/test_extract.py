"""Extraction tests against real PDF, Word and text files built on the fly."""

from pathlib import Path

import pytest
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from docpipe.extract import ExtractionError, UnsupportedFileType, discover, extract


def _pdf(path: Path, pages: list[str]) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Test PDF")
    for text in pages:
        c.drawString(50, 700, text)
        c.showPage()
    c.save()
    return path


def test_pdf_pages_and_title(tmp_path):
    doc = extract(_pdf(tmp_path / "a.pdf", ["first page text", "second page text"]))
    assert doc.source_type == "pdf"
    assert doc.page_count == 2
    assert "second page text" in doc.pages[1]
    assert doc.title == "Test PDF"


def test_docx_paragraphs_and_title(tmp_path):
    d = Document()
    d.core_properties.title = "Memo"
    d.add_paragraph("Hello")
    d.add_paragraph("World")
    d.save(str(tmp_path / "m.docx"))
    doc = extract(tmp_path / "m.docx")
    assert doc.title == "Memo"
    assert doc.pages == ["Hello\n\nWorld"]


def test_markdown_title_from_heading(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("# Policy Title\n\nBody")
    assert extract(p).title == "Policy Title"


def test_unsupported_type(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b")
    with pytest.raises(UnsupportedFileType):
        extract(p)


def test_corrupt_pdf_raises_extraction_error(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not really a pdf")
    with pytest.raises(ExtractionError):
        extract(p)


def test_discover_is_sorted_and_skips_hidden(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / ".secret").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.md").write_text("c")
    assert [p.name for p in discover(tmp_path)] == ["a.txt", "b.txt", "c.md"]
