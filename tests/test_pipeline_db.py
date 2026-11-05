"""End-to-end tests against a real PostgreSQL database.

Set TEST_DATABASE_URL to a database the tests may wipe, e.g.
  TEST_DATABASE_URL=postgresql://docpipe:docpipe@localhost:5432/docpipe_test
Tests are skipped when it is not set.
"""

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest

from docpipe.config import Settings
from docpipe.embed import HashingEmbedder
from docpipe.pipeline import run_ingestion
from docpipe.store import Store

DB_URL = os.getenv("TEST_DATABASE_URL")
SAMPLES = Path(__file__).resolve().parent.parent / "samples"

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

TABLES = ["quality_results", "quarantine", "chunks", "documents", "ingestion_runs"]


@pytest.fixture(params=["auto", "array"])
def store(request):
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        for t in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    s = Store.connect(DB_URL, request.param)
    s.migrate()
    yield s
    s.close()


@pytest.fixture
def settings():
    return Settings(database_url=DB_URL, chunk_size=80, chunk_overlap=15)


def _scalar(store, sql, *params):
    return store.conn.execute(sql, params).fetchone()[0]


def test_sample_corpus_loads_and_reconciles(store, settings):
    report = run_ingestion(SAMPLES, store, settings)
    assert report.ok
    assert report.files_seen == 7
    assert report.docs_loaded == 4  # txt, md, pdf, docx
    assert report.docs_skipped == 1  # re-uploaded copy of the retention guideline
    assert report.docs_quarantined == 2  # .zip and the text-less "scanned" PDF
    assert report.reconciliation["files_accounted_for"]
    status = _scalar(store, "SELECT status FROM ingestion_runs WHERE run_id = %s", report.run_id)
    assert status == "succeeded"


def test_rerun_is_idempotent(store, settings):
    first = run_ingestion(SAMPLES, store, settings)
    chunks_before = _scalar(store, "SELECT count(*) FROM chunks")
    second = run_ingestion(SAMPLES, store, settings)
    assert second.ok
    assert second.docs_loaded == 0
    assert second.docs_skipped == first.docs_loaded + first.docs_skipped
    assert _scalar(store, "SELECT count(*) FROM chunks") == chunks_before


def test_no_personal_data_reaches_the_store(store, settings):
    run_ingestion(SAMPLES, store, settings)
    leaked = _scalar(
        store,
        "SELECT count(*) FROM chunks WHERE text LIKE '%%@%%' OR text LIKE '%%4111%%' "
        "OR text LIKE '%%712 345%%' OR text LIKE '%%A012345678Z%%'",
    )
    assert leaked == 0
    counts = _scalar(store, "SELECT pii_redactions FROM documents WHERE source_type = 'md'")
    assert counts["EMAIL"] == 1 and counts["CARD_NUMBER"] == 1 and counts["KRA_PIN"] == 1


def test_quarantine_records_reasons_and_failed_checks(store, settings):
    run_ingestion(SAMPLES, store, settings)
    reasons = dict(
        store.conn.execute(
            "SELECT reverse(split_part(reverse(source_path), '/', 1)), reason FROM quarantine"
        ).fetchall()
    )
    assert reasons == {
        "branch-photos.zip": "unsupported_type",
        "scanned-statement.pdf": "quality_check_failed",
    }
    failed = {
        r[0]
        for r in store.conn.execute(
            "SELECT check_name FROM quality_results WHERE source_path LIKE '%%scanned%%' AND NOT passed"
        ).fetchall()
    }
    assert "pdf_text_density" in failed


def test_running_headers_are_not_stored(store, settings):
    run_ingestion(SAMPLES, store, settings)
    hits = _scalar(
        store,
        "SELECT count(*) FROM chunks WHERE text LIKE '%%Product FAQ%%' OR text LIKE '%%Page 1 of%%'",
    )
    assert hits == 0


def test_search_finds_the_right_document(store, settings):
    run_ingestion(SAMPLES, store, settings)
    query = HashingEmbedder().embed(["is there an early repayment penalty"])[0]
    top = store.search(query, k=1)[0]
    assert top["title"] == "Jenga Biashara Loan FAQ"
    assert "early repayment" in top["text"].lower()


def test_retention_purge_removes_expired_documents_and_chunks(store, settings):
    run_ingestion(SAMPLES, store, settings)
    assert store.purge_expired(date.today()) == 0
    future = date.today() + timedelta(days=settings.retention_days + 1)
    assert store.purge_expired(future) == 4
    assert _scalar(store, "SELECT count(*) FROM chunks") == 0


def test_failed_reconciliation_marks_run_failed(store, settings, tmp_path, monkeypatch):
    shutil.copy(SAMPLES / "customer-onboarding-policy.md", tmp_path)
    real = store.run_totals_from_tables
    monkeypatch.setattr(
        store,
        "run_totals_from_tables",
        lambda run_id: {**real(run_id), "chunks_loaded": -1},
    )
    report = run_ingestion(tmp_path, store, settings)
    assert not report.ok
    status = _scalar(store, "SELECT status FROM ingestion_runs WHERE run_id = %s", report.run_id)
    assert status == "failed"
