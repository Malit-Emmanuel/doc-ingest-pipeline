"""Command-line interface: docpipe migrate | ingest | search | runs | purge-expired."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .embed import get_embedder
from .pipeline import run_ingestion
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docpipe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="create or update the database schema")
    p_ingest = sub.add_parser("ingest", help="ingest a file or a folder of documents")
    p_ingest.add_argument("path", type=Path)
    p_search = sub.add_parser("search", help="semantic search over ingested chunks")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_runs = sub.add_parser("runs", help="show recent ingestion runs")
    p_runs.add_argument("-n", type=int, default=10)
    sub.add_parser("purge-expired", help="delete documents past their retention date")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    settings = Settings.from_env()
    store = Store.connect(settings.database_url, settings.vector_backend)
    try:
        store.migrate()
        if args.command == "migrate":
            print(f"schema ready (vector backend: {store.backend})")
        elif args.command == "ingest":
            if not args.path.exists():
                parser.error(f"path not found: {args.path}")
            report = run_ingestion(args.path, store, settings)
            print(
                json.dumps(
                    {
                        "run_id": report.run_id,
                        "ok": report.ok,
                        **report.counts(),
                        "reconciliation": report.reconciliation,
                    },
                    indent=2,
                )
            )
            return 0 if report.ok else 1
        elif args.command == "search":
            vec = get_embedder(settings.embedder).embed([args.query])[0]
            for hit in store.search(vec, args.k):
                snippet = hit["text"][:160] + ("..." if len(hit["text"]) > 160 else "")
                print(f"{hit['score']:.3f}  {hit['title']}  [chunk {hit['chunk_index']}]\n       {snippet}\n")
        elif args.command == "runs":
            for r in store.recent_runs(args.n):
                print(json.dumps(r, default=str))
        elif args.command == "purge-expired":
            print(f"purged {store.purge_expired()} expired document(s)")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
