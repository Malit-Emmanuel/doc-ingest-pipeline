-- docpipe schema. {embedding_type} is vector(384) with pgvector, or real[] without it.

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id            uuid PRIMARY KEY,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'succeeded', 'failed')),
    source            text NOT NULL,
    embedder          text NOT NULL,
    files_seen        integer NOT NULL DEFAULT 0,
    docs_loaded       integer NOT NULL DEFAULT 0,
    docs_skipped      integer NOT NULL DEFAULT 0,
    docs_quarantined  integer NOT NULL DEFAULT 0,
    chunks_loaded     integer NOT NULL DEFAULT 0,
    reconciliation    jsonb,
    settings          jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id          uuid PRIMARY KEY,
    content_sha256  char(64) NOT NULL UNIQUE,
    source_path     text NOT NULL,
    source_type     text NOT NULL,
    title           text NOT NULL,
    page_count      integer NOT NULL,
    char_count      integer NOT NULL,
    pii_redactions  jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    run_id          uuid NOT NULL REFERENCES ingestion_runs(run_id),
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    retain_until    date NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     uuid PRIMARY KEY,
    doc_id       uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    text         text NOT NULL,
    word_count   integer NOT NULL CHECK (word_count > 0),
    embedding    {embedding_type} NOT NULL,
    UNIQUE (doc_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS quality_results (
    id          bigserial PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES ingestion_runs(run_id),
    source_path text NOT NULL,
    doc_id      uuid REFERENCES documents(doc_id) ON DELETE SET NULL,
    check_name  text NOT NULL,
    passed      boolean NOT NULL,
    blocking    boolean NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    checked_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quarantine (
    id           bigserial PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES ingestion_runs(run_id),
    source_path  text NOT NULL,
    reason       text NOT NULL,
    detail       jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    quarantined_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS documents_retain_idx ON documents (retain_until);
CREATE INDEX IF NOT EXISTS quality_run_idx ON quality_results (run_id);
