"""Faits durables (sémantiques + épisodiques) : store Chroma, isolation par `user_id`.

Chroma réel (`CHROMA_URL`) en prod avec embeddings multilingues e5 ; repli
`EphemeralClient` hors-ligne (tests/CI, pas de service externe) avec l'embedder
par défaut de Chroma — même pattern que `kb_store.get_kb()`. Les filtres
`where=` sont des correspondances exactes sur les métadonnées, jamais de la
similarité : ils garantissent une suppression/inspection vérifiables (R5/R6).
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import urlparse

from chromadb.api.models.Collection import Collection

_COLLECTION_NAME = "velmo_memory_facts"


def _client(chroma_url: str | None = None) -> Any:
    import chromadb

    url = chroma_url or os.getenv("CHROMA_URL")
    if not url:
        return chromadb.EphemeralClient()
    parsed = urlparse(url)
    return chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)


def _embedding_function(chroma_url: str | None = None) -> Any | None:
    if not (chroma_url or os.getenv("CHROMA_URL")):
        return None  # embedder par défaut de Chroma (léger, hors-ligne)
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )


def get_collection(chroma_url: str | None = None) -> Collection:
    """Collection Chroma des faits durables (créée si absente)."""
    client = _client(chroma_url)
    kwargs: dict[str, Any] = {}
    embedding_function = _embedding_function(chroma_url)
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(_COLLECTION_NAME, **kwargs)  # type: ignore[no-any-return]


def remember(collection: Collection, user_id: str, key: str, value: str) -> None:
    """Enregistre un fait durable ; remplace toute version précédente du même `key` (FR-009)."""
    collection.delete(where={"$and": [{"user_id": user_id}, {"key": key}]})
    collection.upsert(
        ids=[f"{user_id}:{key}:{uuid.uuid4().hex[:8]}"],
        documents=[f"{key}: {value}"],
        metadatas=[{"user_id": user_id, "fact_type": "preference", "key": key}],
    )


def store_excerpt(collection: Collection, user_id: str, text: str) -> None:
    """Stocke un extrait de fenêtre courte évincé, tel quel (R4 : transfert vers le long terme)."""
    collection.upsert(
        ids=[f"{user_id}:excerpt:{uuid.uuid4().hex}"],
        documents=[text],
        metadatas=[{"user_id": user_id, "fact_type": "episodic_excerpt", "key": ""}],
    )


def search(
    collection: Collection, user_id: str, query: str, k: int = 5, fact_type: str | None = None
) -> list[str]:
    """Recherche sémantique des faits/extraits pertinents pour cet utilisateur.

    La recherche par similarité (HNSW) n'est pas garantie exhaustive même avec un
    filtre `where` exact : à ne réserver qu'aux entrées pour lesquelles un rappel
    partiel est acceptable (extraits épisodiques). Les faits qui doivent être
    systématiquement disponibles (`preference`) passent par `preferences()`.
    """
    where: Any = (
        {"user_id": user_id}
        if fact_type is None
        else {"$and": [{"user_id": user_id}, {"fact_type": fact_type}]}
    )
    result = collection.query(query_texts=[query], n_results=k, where=where)
    documents = result.get("documents") or [[]]
    return list(documents[0])


def preferences(collection: Collection, user_id: str) -> dict[str, str]:
    """Tous les faits `preference` d'un utilisateur (lecture exacte, jamais de similarité)."""
    where: Any = {"$and": [{"user_id": user_id}, {"fact_type": "preference"}]}
    got = collection.get(where=where)
    documents = got["documents"] or []
    metadatas = got["metadatas"] or []
    return {
        str(meta.get("key", "")): doc
        for doc, meta in zip(documents, metadatas)
        if meta and meta.get("key")
    }


def all_facts(collection: Collection, user_id: str) -> list[dict[str, Any]]:
    """Tous les faits d'un utilisateur (traçabilité, R6)."""
    got = collection.get(where={"user_id": user_id})
    documents = got["documents"] or []
    metadatas = got["metadatas"] or []
    return [
        {"id": id_, "content": doc, **(meta or {})}
        for id_, doc, meta in zip(got["ids"], documents, metadatas)
    ]


def delete_matching(collection: Collection, user_id: str, target: str) -> int:
    """Supprime les faits d'un utilisateur dont la clé ou le contenu contiennent `target` (R5)."""
    target_low = target.lower()
    matches = [
        f
        for f in all_facts(collection, user_id)
        if target_low in f["content"].lower() or target_low in f.get("key", "").lower()
    ]
    if matches:
        collection.delete(ids=[f["id"] for f in matches])
    return len(matches)
