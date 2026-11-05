"""Orchestration: discover -> extract -> clean -> redact -> chunk -> embed -> check -> load.

Each document is processed independently: one bad file is quarantined with a reason
and the run carries on. At the end the run's own tally is reconciled against what is
actually in the database, and the run is marked failed if they disagree.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .chunk import chunk_text
from .clean import clean_pages
from .config import EMBEDDING_DIM, Settings
from .embed import Embedder, get_embedder
from .extract import ExtractionError, UnsupportedFileType, discover, extract
from .quality import blocking_failures, check_document
from .redact import redact
from .store import Store

log = logging.getLogger("docpipe")


@dataclass
class RunReport:
    run_id: str
    files_seen: int = 0
    docs_loaded: int = 0
    docs_skipped: int = 0
    docs_quarantined: int = 0
    chunks_loaded: int = 0
    reconciliation: dict = field(default_factory=dict)
    ok: bool = False

    def counts(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "docs_loaded": self.docs_loaded,
            "docs_skipped": self.docs_skipped,
            "docs_quarantined": self.docs_quarantined,
            "chunks_loaded": self.chunks_loaded,
        }


def _event(event: str, **fields) -> None:
    log.info(json.dumps({"event": event, **fields}, default=str))


def run_ingestion(
    source: Path, store: Store, settings: Settings, embedder: Embedder | None = None
) -> RunReport:
    embedder = embedder or get_embedder(settings.embedder)
    if embedder.dim != EMBEDDING_DIM:
        raise ValueError(f"embedder dimension {embedder.dim} does not match schema {EMBEDDING_DIM}")

    run_id = store.start_run(str(source), embedder.name, settings.public_dict())
    report = RunReport(run_id=str(run_id))
    _event("run_started", run_id=run_id, source=source, backend=store.backend)

    try:
        for path in discover(source):
            report.files_seen += 1
            _process_file(path, run_id, store, settings, embedder, report)
    finally:
        expected = {
            "docs_loaded": report.docs_loaded,
            "chunks_loaded": report.chunks_loaded,
            "docs_quarantined": report.docs_quarantined,
        }
        actual = store.run_totals_from_tables(run_id)
        accounted = report.docs_loaded + report.docs_skipped + report.docs_quarantined
        report.reconciliation = {
            "expected": expected,
            "in_database": actual,
            "files_accounted_for": accounted == report.files_seen,
        }
        report.ok = expected == actual and accounted == report.files_seen
        store.finish_run(run_id, report.counts(), report.reconciliation, report.ok)
        _event("run_finished", run_id=run_id, ok=report.ok, **report.counts())
    return report


def _process_file(path, run_id, store: Store, settings: Settings, embedder, report) -> None:
    source_path = str(path)

    try:
        doc = extract(path)
    except UnsupportedFileType as exc:
        _quarantine(store, report, run_id, source_path, "unsupported_type", {"error": str(exc)})
        return
    except ExtractionError as exc:
        _quarantine(store, report, run_id, source_path, "extraction_failed", {"error": str(exc)})
        return

    text = clean_pages(doc.pages)
    redaction = redact(text)
    text = redaction.text

    # Hash the cleaned, redacted content: the same document re-uploaded under another
    # name is recognised and skipped, which keeps re-runs idempotent.
    sha256 = hashlib.sha256(text.encode()).hexdigest()
    if store.has_document(sha256):
        report.docs_skipped += 1
        _event("doc_skipped_duplicate", path=source_path, sha256=sha256[:12])
        return

    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    embeddings = embedder.embed([c.text for c in chunks]) if chunks else None

    checks = check_document(
        text=text,
        source_type=doc.source_type,
        page_count=doc.page_count,
        chunks=chunks,
        embeddings=embeddings,
        expected_dim=EMBEDDING_DIM,
        max_chunk_words=settings.chunk_size,
        min_doc_chars=settings.min_doc_chars,
        min_chars_per_pdf_page=settings.min_chars_per_pdf_page,
    )
    failed = blocking_failures(checks)
    if failed:
        _quarantine(
            store,
            report,
            run_id,
            source_path,
            "quality_check_failed",
            {"failed_checks": [f.name for f in failed]},
            checks,
        )
        return

    store.load_document(
        run_id=run_id,
        sha256=sha256,
        source_path=source_path,
        source_type=doc.source_type,
        title=doc.title,
        page_count=doc.page_count,
        char_count=len(text),
        pii_redactions=redaction.counts,
        retention_days=settings.retention_days,
        chunks=chunks,
        embeddings=embeddings,
        checks=checks,
    )
    report.docs_loaded += 1
    report.chunks_loaded += len(chunks)
    _event("doc_loaded", path=source_path, chunks=len(chunks), redactions=redaction.counts)


def _quarantine(store, report, run_id, source_path, reason, detail, checks=None) -> None:
    store.quarantine(run_id, source_path, reason, detail, checks)
    report.docs_quarantined += 1
    _event("doc_quarantined", path=source_path, reason=reason, **detail)
