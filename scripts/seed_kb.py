"""Ingestion de la FAQ Velmo (kb/docs/*.md) dans Chroma.

Usage : uv run python scripts/seed_kb.py
Nécessite l'extra `vector` (chromadb + sentence-transformers) et un service Chroma.
"""

from __future__ import annotations

import os
from pathlib import Path

KB_DOCS_DIR = Path(__file__).resolve().parent.parent / "kb" / "docs"


def main() -> None:
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.HttpClient(
        host=os.getenv("CHROMA_HOST", "chroma"), port=int(os.getenv("CHROMA_PORT", "8000"))
    )
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    collection = client.get_or_create_collection("velmo_faq", embedding_function=embedder)

    docs, ids, metas = [], [], []
    for path in sorted(KB_DOCS_DIR.glob("*.md")):
        docs.append(path.read_text(encoding="utf-8"))
        ids.append(path.stem)
        metas.append({"source": path.name})

    collection.upsert(documents=docs, ids=ids, metadatas=metas)
    print(f"FAQ ingérée dans Chroma : {len(docs)} documents.")


if __name__ == "__main__":
    main()
