"""FactStore: the long-term memory backend, on the kb_store pattern.

``LocalFactStore`` (a dict per user_id) is the offline/test backend; a user's
facts live in a dict another user can't reach — R3 isolation by construction.
``ChromaFactStore`` is the prod backend: a dedicated Chroma collection
(``velmo_memory``, distinct from the FAQ's ``velmo_faq``) where isolation rests on
a ``where={"user_id": …}`` filter applied in one central place. ``get_fact_store``
selects by ``CHROMA_URL``, exactly like ``get_kb()``.
"""

from __future__ import annotations

import hashlib
import os
from typing import Protocol

from velmo.kb_store import parse_chroma_url

from .facts import Fact, is_semantic


class FactStore(Protocol):
    def write(self, fact: Fact) -> Fact: ...
    def search(
        self, user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5
    ) -> list[Fact]: ...
    def all(self, user_id: str) -> list[Fact]: ...
    def delete(self, user_id: str, target: str | None = None) -> int: ...


def semantic_storage_key(fact: Fact) -> str:
    return f"{fact.user_id}:{fact.fact_type}:{fact.key}"


def episodic_storage_key(fact: Fact) -> str:
    """Content-derived id: re-extracting the same content is idempotent, while
    two distinct episodic contents coexist (FR-009 episodic append)."""
    digest = hashlib.sha256(fact.content.encode("utf-8")).hexdigest()[:16]
    return f"{fact.user_id}:{fact.fact_type}:{fact.key}:{digest}"


def _matches(fact: Fact, needle: str | None) -> bool:
    return needle is None or needle in fact.key.lower() or needle in fact.content.lower()


class LocalFactStore:
    """Offline backend: one dict of facts per user_id."""

    def __init__(self) -> None:
        self._by_user: dict[str, dict[str, Fact]] = {}

    def write(self, fact: Fact) -> Fact:
        bucket = self._by_user.setdefault(fact.user_id, {})
        if is_semantic(fact.fact_type):
            storage_key = semantic_storage_key(fact)
            existing = bucket.get(storage_key)
            if existing is not None:
                fact = fact.model_copy(update={"created_at": existing.created_at})
        else:
            storage_key = episodic_storage_key(fact)
        bucket[storage_key] = fact
        return fact

    def all(self, user_id: str) -> list[Fact]:
        facts = list(self._by_user.get(user_id, {}).values())
        facts.sort(key=lambda f: f.updated_at, reverse=True)
        return facts

    def search(
        self, user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5
    ) -> list[Fact]:
        facts = self.all(user_id)
        if fact_types:
            allowed = set(fact_types)
            facts = [f for f in facts if f.fact_type in allowed]
        return facts[:k]

    def delete(self, user_id: str, target: str | None = None) -> int:
        bucket = self._by_user.get(user_id, {})
        needle = target.lower() if target else None
        to_delete = [key for key, fact in bucket.items() if _matches(fact, needle)]
        for key in to_delete:
            del bucket[key]
        return len(to_delete)


class ChromaFactStore:
    """Prod backend: a dedicated Chroma collection, isolated by a user_id filter.

    The ``where={"user_id": …}`` filter is applied here and only here — that is
    the single line R3 isolation depends on in production.
    """

    def __init__(self, collection) -> None:
        self._collection = collection

    def write(self, fact: Fact) -> Fact:
        if is_semantic(fact.fact_type):
            storage_key = semantic_storage_key(fact)
            existing = self._collection.get(ids=[storage_key])
            metas = existing.get("metadatas") or []
            if metas:
                fact = fact.model_copy(
                    update={"created_at": metas[0].get("created_at", fact.created_at)}
                )
        else:
            storage_key = episodic_storage_key(fact)
        self._collection.upsert(
            ids=[storage_key], documents=[fact.content], metadatas=[fact.model_dump()]
        )
        return fact

    def all(self, user_id: str) -> list[Fact]:
        got = self._collection.get(where={"user_id": user_id})
        facts = [Fact(**meta) for meta in (got.get("metadatas") or [])]
        facts.sort(key=lambda f: f.updated_at, reverse=True)
        return facts

    def search(
        self, user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5
    ) -> list[Fact]:
        where: dict = {"user_id": user_id}
        if fact_types:
            where = {"$and": [{"user_id": user_id}, {"fact_type": {"$in": list(fact_types)}}]}
        result = self._collection.query(query_texts=[query], n_results=k, where=where)
        metas = (result.get("metadatas") or [[]])[0]
        return [Fact(**meta) for meta in metas]

    def delete(self, user_id: str, target: str | None = None) -> int:
        got = self._collection.get(where={"user_id": user_id})
        ids = got.get("ids") or []
        metas = got.get("metadatas") or []
        needle = target.lower() if target else None
        to_delete = [id_ for id_, meta in zip(ids, metas) if _matches(Fact(**meta), needle)]
        if to_delete:
            self._collection.delete(ids=to_delete)
        return len(to_delete)


def get_fact_store() -> FactStore:
    """Return the Chroma-backed store if configured, else the in-memory one."""
    if not os.getenv("CHROMA_URL"):
        return LocalFactStore()
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        return LocalFactStore()

    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    collection = client.get_or_create_collection("velmo_memory", embedding_function=embedder)
    return ChromaFactStore(collection)
