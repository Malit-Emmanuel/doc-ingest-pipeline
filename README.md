# docpipe – document ingestion pipeline for retrieval-augmented AI

[![CI](https://github.com/Malit-Emmanuel/doc-ingest-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/Malit-Emmanuel/doc-ingest-pipeline/actions/workflows/ci.yml)

docpipe turns unstructured documents (PDF, Word, Markdown and plain text) into clean, searchable chunks stored in **PostgreSQL with pgvector**, ready for retrieval-augmented generation (RAG) and other generative AI applications.

It is built the way a regulated organisation such as a bank needs this kind of pipeline built. **Personal data is redacted before anything is stored. Every document passes data-quality checks or goes to quarantine with a reason. Re-runs are idempotent. Every run reconciles its own tally against the database, and every record carries a retention date.**

## Architecture

```mermaid
flowchart LR
    A[Source files<br/>PDF · DOCX · MD · TXT] --> B[Extract<br/>per page]
    B --> C[Clean<br/>normalise, drop headers/footers]
    C --> D[Redact PII<br/>email, phone, KRA PIN, ID, card]
    D --> E{Already loaded?<br/>SHA-256 of content}
    E -- yes --> S[Skip]
    E -- no --> F[Chunk<br/>overlapping, sentence-aware]
    F --> G[Embed<br/>384-dim vectors]
    G --> H{Quality checks}
    H -- blocking failure --> Q[(quarantine)]
    H -- pass --> L[(documents + chunks<br/>pgvector, HNSW index)]
    L --> R[Reconcile run<br/>tally vs database]
    Q --> R
    S --> R
    R --> I[(ingestion_runs)]
```

| Stage | Module | What it guarantees |
| --- | --- | --- |
| Extract | `extract.py` | Per-page text from PDF, DOCX, MD and TXT. Corrupt or unsupported files are quarantined, not crashed on. |
| Clean | `clean.py` | Unicode normalisation, control characters removed, hyphenated line breaks rejoined, running headers, footers and page numbers dropped. |
| Redact | `redact.py` | Emails, Kenyan phone numbers, KRA PINs, labelled national ID numbers and Luhn-valid card numbers are replaced with tags such as `[EMAIL]` before storage. Counts are kept per document. |
| Deduplicate | `pipeline.py` | SHA-256 of the cleaned, redacted content. The same document under another file name is skipped, so re-runs never duplicate data. |
| Chunk | `chunk.py` | Overlapping chunks that follow paragraph and sentence boundaries, with a hard size limit. |
| Embed | `embed.py` | Pluggable embedders with the same 384 dimensions: an offline, deterministic hashing embedder (default, used in CI) and `all-MiniLM-L6-v2`. |
| Quality | `quality.py` | Minimum text length, text density per PDF page (catches scanned PDFs that need OCR), chunk size bounds, no PII residue, duplicate-chunk ratio and embedding integrity. Every result is stored. |
| Load | `store.py` | Each document, its chunks and its check results are written in **one transaction**. Run lineage, quarantine and retention purge are included. |

## Data model

| Table | Purpose |
| --- | --- |
| `ingestion_runs` | One row per run: source, embedder, settings, counts, reconciliation result and status. |
| `documents` | One row per unique document: content hash, source, page and character counts, PII redaction counts, `retain_until`. |
| `chunks` | Chunk text and `embedding vector(384)` with an HNSW cosine index. Deleted with their document. |
| `quality_results` | Every check for every document in every run: name, pass/fail, blocking flag and details. |
| `quarantine` | Files that were not loaded, with the reason (`unsupported_type`, `extraction_failed`, `quality_check_failed`) and details. |

## Quick start

```bash
docker compose up -d                  # PostgreSQL 16 + pgvector
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env && export $(grep -v '^#' .env | xargs)

docpipe ingest samples                # load the sample corpus
docpipe search "how long are call recordings kept"
docpipe runs                          # recent runs with counts
docpipe purge-expired                 # apply the retention policy
```

On the sample corpus a run reports:

```json
{
  "ok": true,
  "files_seen": 7,
  "docs_loaded": 4,
  "docs_skipped": 1,
  "docs_quarantined": 2,
  "reconciliation": { "files_accounted_for": true, "...": "..." }
}
```

That run shows four documents loaded (PDF, Word, Markdown, text) and one re-uploaded duplicate skipped. It also shows two files quarantined: a `.zip` and a text-less "scanned" PDF that fails the text-density check. The sample organisation, Mwangaza Savings Bank, is fictional, and all personal data in the samples is fake.

To use a real semantic model instead of the hashing embedder, run `pip install -e ".[models]"` and set `EMBEDDER=sentence-transformers`. No schema change is needed.

## Configuration

All settings come from environment variables; see [`.env.example`](.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | local compose database | PostgreSQL connection string |
| `VECTOR_BACKEND` | `auto` | `pgvector`, `array` (plain `real[]` fallback) or `auto` |
| `EMBEDDER` | `hashing` | `hashing` or `sentence-transformers` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `200` / `40` | Chunk size and overlap in words |
| `MIN_DOC_CHARS` | `50` | Minimum characters for a document to load |
| `MIN_CHARS_PER_PDF_PAGE` | `20` | Below this, a PDF is treated as scanned and quarantined |
| `RETENTION_DAYS` | `365` | Days until a document is eligible for `purge-expired` |

## Testing and CI

```bash
pytest                                                    # unit tests
TEST_DATABASE_URL=postgresql://docpipe:docpipe@localhost:5432/docpipe_test pytest   # + database tests
```

The suite has 48 tests. The database tests run against a real PostgreSQL instance with both vector backends. They cover reconciliation, idempotent re-runs, that no personal data reaches the store, quarantine reasons, header and footer removal, search relevance, retention purges, and a run being marked failed when reconciliation does not match.

GitHub Actions runs linting (`ruff`), the full test suite against a `pgvector/pgvector:pg16` service, and an end-to-end ingest and search on the sample corpus on every push.

## Design decisions

- **Redact before embed.** Text and vectors in a vector store end up in prompts, caches and logs, where they are hard to delete. Removing personal data first is cheaper and safer than trying to clean it out later. This follows the data-minimisation principle of Kenya's Data Protection Act, 2019.
- **Quarantine, don't crash.** One bad file should not stop a nightly run. Each failure is recorded with a machine-readable reason so it can be reported on and fixed.
- **Reconcile every run.** The pipeline compares what it believes it loaded with what is actually in the database, and marks the run `failed` on any mismatch.
- **One transaction per document.** A document is never left half-loaded with some chunks missing.
- **Deterministic default embedder.** Tests and CI need no model download and give the same result every time. The production model is a configuration switch away.

## Limits and next steps

- PII detection is pattern-based. It does not detect personal names or free-text addresses; a named-entity model such as spaCy or Microsoft Presidio would be the next step.
- Scanned PDFs are detected and quarantined, but not yet processed. Next step: an OCR stage (Tesseract) feeding the same clean, redact and chunk path.
- Voice: add a speech-to-text stage (for example, Whisper) that outputs transcripts into the same path.
- Orchestration: run `docpipe ingest` on a schedule from Airflow, or as a Databricks job reading from object storage.

## Licence

MIT
