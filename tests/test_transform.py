"""Unit tests for the pure stages: cleaning, redaction, chunking, embedding and quality checks."""

import numpy as np
import pytest

from docpipe.chunk import chunk_text
from docpipe.clean import clean_pages, clean_text, remove_repeated_lines
from docpipe.embed import HashingEmbedder
from docpipe.quality import blocking_failures, check_document
from docpipe.redact import luhn_valid, redact

# ---- cleaning ---------------------------------------------------------------------------


def test_clean_text_normalises_whitespace_and_joins_hyphenated_breaks():
    raw = "Data   quality\tmatters.\r\nWell-struc-\ntured   pipelines\n\n\n\nwin.\x00"
    assert clean_text(raw) == "Data quality matters.\nWell-structured pipelines\n\nwin."


def test_clean_text_drops_page_number_lines():
    assert clean_text("Intro\nPage 2 of 9\n3\nBody") == "Intro\nBody"


def test_repeated_headers_and_footers_are_removed():
    pages = [f"ACME Bank - Internal\nContent of page {i}\nConfidential" for i in range(4)]
    cleaned = remove_repeated_lines(pages)
    assert all("ACME Bank" not in p and "Confidential" not in p for p in cleaned)
    assert "Content of page 2" in cleaned[2]


def test_short_documents_keep_their_lines():
    pages = ["Title\nA", "Title\nB"]
    assert remove_repeated_lines(pages) == pages


def test_clean_pages_joins_pages_with_blank_line():
    assert clean_pages(["one", "", "two"]) == "one\n\ntwo"


# ---- redaction --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,label",
    [
        ("mail me at jane.doe+bank@example.co.ke today", "EMAIL"),
        ("call +254 712 345 678 now", "PHONE"),
        ("call 0712345678 now", "PHONE"),
        ("call 0110-123-456 now", "PHONE"),
        ("PIN A012345678Z on file", "KRA_PIN"),
        ("ID No: 23456789 verified", "NATIONAL_ID"),
        ("card 4111 1111 1111 1111 used", "CARD_NUMBER"),
        ("card 5500-0000-0000-0004 used", "CARD_NUMBER"),
    ],
)
def test_redact_detects_personal_data(text, label):
    result = redact(text)
    assert result.counts == {label: 1}
    assert f"[{label}]" in result.text


def test_redact_leaves_ordinary_numbers_alone():
    text = "Loans from 50000 to 2000000 shillings over 24 months; reference 1234567890123."
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


def test_luhn():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


# ---- chunking ---------------------------------------------------------------------------


def _paragraphs(n_paras: int, words_each: int) -> str:
    return "\n\n".join(
        " ".join(f"p{p}w{w}." if w == words_each - 1 else f"p{p}w{w}" for w in range(words_each))
        for p in range(n_paras)
    )


def test_chunks_respect_size_and_overlap():
    text = _paragraphs(10, 60)
    chunks = chunk_text(text, size=150, overlap=30)
    assert len(chunks) > 1
    assert all(c.word_count <= 150 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        shared = set(prev.text.split()[-30:]) & set(nxt.text.split()[:30])
        assert shared, "consecutive chunks should overlap"


def test_every_word_is_covered():
    text = _paragraphs(7, 45)
    chunks = chunk_text(text, size=100, overlap=20)
    covered = set(" ".join(c.text for c in chunks).split())
    assert covered == set(text.split())


def test_oversized_paragraph_is_split():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_text(text, size=200, overlap=0)
    assert all(c.word_count <= 200 for c in chunks)
    assert sum(c.word_count for c in chunks) == 1000


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n\n  ") == []


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_text("a b c", size=10, overlap=10)


# ---- embedding --------------------------------------------------------------------------


def test_hashing_embedder_is_deterministic_and_normalised():
    emb = HashingEmbedder()
    a = emb.embed(["early repayment of the loan", "call recordings retention"])
    b = emb.embed(["early repayment of the loan", "call recordings retention"])
    assert a.shape == (2, 384)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0, rtol=1e-5)


def test_hashing_embedder_ranks_related_text_higher():
    emb = HashingEmbedder()
    q, related, unrelated = emb.embed(
        [
            "is there an early repayment penalty on the loan",
            "early repayment is allowed and there is no early repayment penalty",
            "branches open at 8.30 am on weekdays",
        ]
    )
    assert q @ related > q @ unrelated


# ---- quality checks ---------------------------------------------------------------------


def _checks(text, source_type="txt", page_count=1, max_words=200):
    chunks = chunk_text(text, size=max_words, overlap=0)
    emb = HashingEmbedder().embed([c.text for c in chunks]) if chunks else None
    return check_document(
        text=text,
        source_type=source_type,
        page_count=page_count,
        chunks=chunks,
        embeddings=emb,
        expected_dim=384,
        max_chunk_words=max_words,
        min_doc_chars=50,
        min_chars_per_pdf_page=20,
    )


def test_good_document_passes_all_blocking_checks():
    assert blocking_failures(_checks("A clear policy document. " * 20)) == []


def test_short_document_is_blocked():
    names = {r.name for r in blocking_failures(_checks("too short"))}
    assert "min_text_length" in names


def test_sparse_pdf_is_flagged_as_scanned():
    text = "Some words that are long enough to pass the length check overall."
    names = {r.name for r in blocking_failures(_checks(text, "pdf", page_count=10))}
    assert names == {"pdf_text_density"}


def test_unredacted_pii_is_blocked():
    text = "Contact the officer at officer@example.com for help with the account. " * 2
    names = {r.name for r in blocking_failures(_checks(text))}
    assert names == {"no_pii_residue"}
