"""Outil FAQ : recherche dans la base de connaissances (RAG)."""

from __future__ import annotations


def search_kb(kb, query: str) -> dict:
    """Cherche une réponse dans la FAQ Velmo et renvoie des extraits sourcés."""
    hits = kb.search(query, k=5)
    if not hits:
        return {"found": False, "query": query, "results": []}
    return {"found": True, "query": query, "results": hits}
