"""Stage 7: load into PostgreSQL (pgvector), plus run lineage, quarantine and retention."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from importlib import resources

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from .chunk import Chunk
from .config import EMBEDDING_DIM
from .quality import CheckResult

PGVECTOR = "pgvector"
ARRAY = "array"


class Store:
    def __init__(self, conn: psycopg.Connection, backend: str) -> None:
        self.conn = conn
        self.backend = backend

    # ---- setup ---------------------------------------------------------------------------

    @classmethod
    def connect(cls, database_url: str, vector_backend: str = "auto") -> Store:
        # autocommit: reads run on their own; every multi-statement write is wrapped in
        # conn.transaction() so it commits or rolls back as a unit.
        conn = psycopg.connect(database_url, autocommit=True)
        backend = cls._detect_backend(conn, vector_backend)
        return cls(conn, backend)

    @staticmethod
    def _detect_backend(conn: psycopg.Connection, requested: str) -> str:
        if requested == ARRAY:
            return ARRAY
        try:
            with conn.transaction():
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            return PGVECTOR
        except psycopg.Error as exc:
            if requested == PGVECTOR:
                raise RuntimeError("pgvector extension is not available in this database") from exc
            return ARRAY

    def migrate(self) -> None:
        existing = self._existing_embedding_type()
        wanted = "vector" if self.backend == PGVECTOR else "_float4"
        if existing and existing != wanted:
            raise RuntimeError(
                f"chunks.embedding is {existing} but backend is {self.backend}; "
                "set VECTOR_BACKEND to match the existing schema"
            )
        ddl = resources.files("docpipe").joinpath("schema.sql").read_text()
        emb_type = f"vector({EMBEDDING_DIM})" if self.backend == PGVECTOR else "real[]"
        with self.conn.transaction():
            self.conn.execute(ddl.format(embedding_type=emb_type))
            if self.backend == PGVECTOR:
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
                    "ON chunks USING hnsw (embedding vector_cosine_ops)"
                )

    def _existing_embedding_type(self) -> str | None:
        row = self.conn.execute(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'chunks' "
            "AND column_name = 'embedding'"
        ).fetchone()
        self.conn.commit()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()

    # ---- runs ----------------------------------------------------------------------------

    def start_run(self, source: str, embedder: str, settings: dict) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO ingestion_runs (run_id, source, embedder, settings) VALUES (%s, %s, %s, %s)",
                (run_id, source, embedder, Jsonb(settings)),
            )
        return run_id

    def finish_run(self, run_id: uuid.UUID, counts: dict, reconciliation: dict, ok: bool) -> None:
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE ingestion_runs SET finished_at = now(), status = %s, files_seen = %s, "
                "docs_loaded = %s, docs_skipped = %s, docs_quarantined = %s, chunks_loaded = %s, "
                "reconciliation = %s WHERE run_id = %s",
                (
                    "succeeded" if ok else "failed",
                    counts["files_seen"],
                    counts["docs_loaded"],
                    counts["docs_skipped"],
                    counts["docs_quarantined"],
                    counts["chunks_loaded"],
                    Jsonb(reconciliation),
                    run_id,
                ),
            )

    def run_totals_from_tables(self, run_id: uuid.UUID) -> dict:
        """Counts taken from the stored data itself, used to reconcile against the run's own tally."""
        row = self.conn.execute(
            """
            SELECT
              (SELECT count(*) FROM documents WHERE run_id = %(r)s),
              (SELECT count(*) FROM chunks c JOIN documents d USING (doc_id) WHERE d.run_id = %(r)s),
              (SELECT count(*) FROM quarantine WHERE run_id = %(r)s)
            """,
            {"r": run_id},
        ).fetchone()
        self.conn.commit()
        return {"docs_loaded": row[0], "chunks_loaded": row[1], "docs_quarantined": row[2]}

    def recent_runs(self, limit: int = 10) -> list[dict]:
        cur = self.conn.execute(
            "SELECT run_id, started_at, status, files_seen, docs_loaded, docs_skipped, "
            "docs_quarantined, chunks_loaded FROM ingestion_runs ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        self.conn.commit()
        return rows

    # ---- documents -----------------------------------------------------------------------

    def has_document(self, sha256: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM documents WHERE content_sha256 = %s", (sha256,)).fetchone()
        self.conn.commit()
        return row is not None

    def load_document(
        self,
        *,
        run_id: uuid.UUID,
        sha256: str,
        source_path: str,
        source_type: str,
        title: str,
        page_count: int,
        char_count: int,
        pii_redactions: dict,
        retention_days: int,
        chunks: list[Chunk],
        embeddings: np.ndarray,
        checks: list[CheckResult],
    ) -> uuid.UUID:
        """Write a document, all its chunks and its check results in one transaction."""
        doc_id = uuid.uuid4()
        retain_until = date.today() + timedelta(days=retention_days)
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO documents (doc_id, content_sha256, source_path, source_type, title, "
                "page_count, char_count, pii_redactions, run_id, retain_until) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    doc_id,
                    sha256,
                    source_path,
                    source_type,
                    title,
                    page_count,
                    char_count,
                    Jsonb(pii_redactions),
                    run_id,
                    retain_until,
                ),
            )
            cast = "::vector" if self.backend == PGVECTOR else ""
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (chunk_id, doc_id, chunk_index, text, word_count, embedding) "
                    f"VALUES (%s, %s, %s, %s, %s, %s{cast})",
                    [
                        (uuid.uuid4(), doc_id, c.index, c.text, c.word_count, self._vec(e))
                        for c, e in zip(chunks, embeddings, strict=True)
                    ],
                )
            self._write_checks(run_id, source_path, doc_id, checks)
        return doc_id

    def quarantine(
        self,
        run_id: uuid.UUID,
        source_path: str,
        reason: str,
        detail: dict,
        checks: list[CheckResult] | None = None,
    ) -> None:
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO quarantine (run_id, source_path, reason, detail) VALUES (%s, %s, %s, %s)",
                (run_id, source_path, reason, Jsonb(detail)),
            )
            if checks:
                self._write_checks(run_id, source_path, None, checks)

    def _write_checks(
        self,
        run_id: uuid.UUID,
        source_path: str,
        doc_id: uuid.UUID | None,
        checks: list[CheckResult],
    ) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO quality_results (run_id, source_path, doc_id, check_name, passed, "
                "blocking, detail) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (run_id, source_path, doc_id, c.name, c.passed, c.blocking, Jsonb(c.detail))
                    for c in checks
                ],
            )

    def _vec(self, v: np.ndarray):
        values = [float(x) for x in v]
        return json.dumps(values) if self.backend == PGVECTOR else values

    # ---- retrieval -----------------------------------------------------------------------

    def search(self, query_vec: np.ndarray, k: int = 5) -> list[dict]:
        if self.backend == PGVECTOR:
            rows = self.conn.execute(
                "SELECT d.title, d.source_path, c.chunk_index, c.text, "
                "1 - (c.embedding <=> %s::vector) AS score "
                "FROM chunks c JOIN documents d USING (doc_id) "
                "ORDER BY c.embedding <=> %s::vector LIMIT %s",
                (self._vec(query_vec), self._vec(query_vec), k),
            ).fetchall()
        else:
            # Fallback: exact cosine similarity in NumPy (fine for small demo corpora).
            data = self.conn.execute(
                "SELECT d.title, d.source_path, c.chunk_index, c.text, c.embedding "
                "FROM chunks c JOIN documents d USING (doc_id)"
            ).fetchall()
            if not data:
                self.conn.commit()
                return []
            matrix = np.array([r[4] for r in data], dtype=np.float32)
            scores = matrix @ query_vec.astype(np.float32)
            order = np.argsort(-scores)[:k]
            rows = [(*data[i][:4], float(scores[i])) for i in order]
        self.conn.commit()
        return [
            {
                "title": r[0],
                "source_path": r[1],
                "chunk_index": r[2],
                "text": r[3],
                "score": round(float(r[4]), 4),
            }
            for r in rows
        ]

    # ---- retention -----------------------------------------------------------------------

    def purge_expired(self, today: date | None = None) -> int:
        """Delete documents past their retention date; chunks go with them (ON DELETE CASCADE)."""
        with self.conn.transaction():
            cur = self.conn.execute("DELETE FROM documents WHERE retain_until < %s", (today or date.today(),))
            return cur.rowcount
