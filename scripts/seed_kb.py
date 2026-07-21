"""Ingestion de la FAQ Velmo (kb/docs/*.md) dans Chroma.

Usage : uv run python scripts/seed_kb.py
Nécessite l'extra `vector` (chromadb + sentence-transformers) et un service Chroma.
"""

from __future__ import annotations

import os
from pathlib import Path

KB_DOCS_DIR = Path(__file__).resolve().parent.parent / "kb" / "docs"


def main() -> None:
    import argparse

    import chromadb
    from chromadb.utils import embedding_functions
    from dotenv import load_dotenv

    from velmo.kb_store import parse_chroma_url

    # Same first line as the other entrypoints (cli.py, demo_app.py): without it
    # the script ignores the CHROMA_URL sitting in the developer's .env and dies
    # on a bare KeyError.
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-empty", action="store_true", help="skip when velmo_faq already has documents"
    )
    args = parser.parse_args()

    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    collection = client.get_or_create_collection("velmo_faq", embedding_function=embedder)

    if args.if_empty and collection.count() > 0:
        print("FAQ already ingested — skipping.")
        return

    docs, ids, metas = [], [], []
    for path in sorted(KB_DOCS_DIR.glob("*.md")):
        docs.append(path.read_text(encoding="utf-8"))
        ids.append(path.stem)
        metas.append({"source": path.name})

    collection.upsert(documents=docs, ids=ids, metadatas=metas)
    print(f"FAQ ingérée dans Chroma : {len(docs)} documents.")


if __name__ == "__main__":
    main()
