# Mémoire long terme (chantier 003) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter l'agent d'une mémoire long terme (faits durables isolés par utilisateur, droit à l'oubli, inspection) via un `FactStore` sur le patron `kb_store`, testable entièrement hors-ligne.

**Architecture:** Un `FactStore` maison à deux backends, calqué sur `LocalKB`/`ChromaKB` : `LocalFactStore` (dict par `user_id`, hors-ligne) et `ChromaFactStore` (collection Chroma `velmo_memory`, prod), choisis par `get_fact_store()` selon `CHROMA_URL`. Les faits (`Fact` pydantic) portent un `fact_type` (sémantique vs épisodique) pilotant la règle de conflit FR-009. Trois outils (`remember_fact`, `forget_user_data`, `inspect_user_memory`) et une recherche par tour injectée dans le `context` déjà existant de `agent_graph.answer` couvrent R2/R5/R6 ; les intentions d'oubli/inspection sont routées dans le nœud déterministe (FR-010, testable sans LLM).

**Tech Stack:** Python 3.11, `uv`, pydantic v2, pytest. Backend prod = Chroma (extra `vector`, déjà présent). Pas de nouvelle dépendance.

## Global Constraints

- Gestionnaire de paquets : `uv` (`uv run pytest …`). Pas de mypy — la vérification est **pytest uniquement**.
- Tout le code (identifiants, docstrings, commentaires, messages de commit) est **en anglais**. Seuls les textes destinés au client final (réponses de l'agent, gabarits de confirmation) sont en français.
- Le cœur tourne **hors-ligne** : `LocalFactStore` en test/dev, aucun Docker/Chroma/Postgres requis pour la suite.
- **Patron `kb_store`** : `FactStore` = interface (`write`/`search`/`all`/`delete`) ; `LocalFactStore` (offline) / `ChromaFactStore` (prod, collection `velmo_memory`) ; `get_fact_store()` choisit selon `CHROMA_URL` — exactement comme `get_kb()`. La FAQ (`kb_store`, collection `velmo_faq`) n'est **pas touchée**.
- **Isolation R3** : hors-ligne structurelle (un dict distinct par `user_id`) ; en prod par filtre `where={"user_id": …}` **centralisé dans `ChromaFactStore`**. Un outil ne choisit jamais `user_id` (fermeture).
- **`fact_type`** ∈ {`preference`, `profile`} (sémantique) ∪ {`order_info`, `dispute`} (épisodique).
- **`Fact`** porte un champ `key` (l'attribut) : le remplacement FR-009 se fait sur `(fact_type, key)`, pas sur `fact_type` seul (un user a plusieurs préférences distinctes).
- **FR-009** : conflit sémantique de même `(fact_type, key)` → **remplace** (garde le plus récent, préserve `created_at`) ; épisodique → **ajoute** (jamais écrasé).
- **FR-010** : la confirmation avant un oubli est un **gabarit déterministe**, jamais générée par le LLM.
- Périmètre : l'extraction automatique par LLM (LangMem), l'ingestion « sans perte » de l'excédent (R4) et l'async sont **différés** (spec §7). L'interface `Extractor` + une impl déterministe sont posées ici. `create_retriever_tool` (lookup LLM en prod) est une option non requise, hors périmètre.

---

### Task 1: Modèle `Fact` et helpers (`memory/facts.py`)

**Files:**
- Create: `src/velmo/memory/facts.py`
- Test: `tests/test_facts.py`

**Interfaces:**
- Consumes: `pydantic.BaseModel`.
- Produces:
  - `class Fact(BaseModel)` : `user_id: str`, `fact_type: str`, `key: str`, `content: str`, `created_at: str`, `updated_at: str`, `source: str = "tool"`, plus `Fact.new(user_id, fact_type, key, content, source="tool") -> Fact`.
  - `SEMANTIC_TYPES: set[str]`, `EPISODIC_TYPES: set[str]`, `FACT_TYPES: set[str]`.
  - `is_semantic(fact_type: str) -> bool`.
  - `render_facts(facts: list[Fact]) -> str`.

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_facts.py` :

```python
"""Unit tests for the Fact model and helpers."""

from __future__ import annotations

from velmo.memory.facts import (
    EPISODIC_TYPES,
    FACT_TYPES,
    SEMANTIC_TYPES,
    Fact,
    is_semantic,
    render_facts,
)


def test_fact_new_sets_timestamps_and_default_source():
    fact = Fact.new("u1", "profile", "pointure", "L")
    assert fact.created_at == fact.updated_at
    assert fact.source == "tool"
    assert fact.user_id == "u1"


def test_is_semantic_classification():
    assert is_semantic("preference") is True
    assert is_semantic("profile") is True
    assert is_semantic("order_info") is False
    assert is_semantic("dispute") is False


def test_fact_type_sets_are_disjoint_and_complete():
    assert SEMANTIC_TYPES.isdisjoint(EPISODIC_TYPES)
    assert FACT_TYPES == SEMANTIC_TYPES | EPISODIC_TYPES


def test_render_facts_lists_key_and_content():
    facts = [Fact.new("u1", "profile", "pointure", "L")]
    rendered = render_facts(facts)
    assert "pointure" in rendered
    assert "L" in rendered


def test_render_facts_empty_is_empty_string():
    assert render_facts([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_facts.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.memory.facts'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/memory/facts.py` :

```python
"""The durable-fact model and its pure helpers.

A ``fact_type`` splits semantic traits (one mutable value per attribute — FR-009
replace) from episodic events (accumulated, never overwritten). The ``key`` field
is the attribute name (``pointure``, ``tutoiement``, ``order``…): FR-009 replaces
on the ``(fact_type, key)`` pair, since a user holds several distinct semantic
facts at once. No backend knowledge lives here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

SEMANTIC_TYPES = {"preference", "profile"}
EPISODIC_TYPES = {"order_info", "dispute"}
FACT_TYPES = SEMANTIC_TYPES | EPISODIC_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_semantic(fact_type: str) -> bool:
    return fact_type in SEMANTIC_TYPES


class Fact(BaseModel):
    user_id: str
    fact_type: str
    key: str
    content: str
    created_at: str
    updated_at: str
    source: str = "tool"

    @classmethod
    def new(
        cls, user_id: str, fact_type: str, key: str, content: str, source: str = "tool"
    ) -> "Fact":
        now = _now()
        return cls(
            user_id=user_id,
            fact_type=fact_type,
            key=key,
            content=content,
            created_at=now,
            updated_at=now,
            source=source,
        )


def render_facts(facts: list[Fact]) -> str:
    """Render facts as a compact bullet list for injection into the LLM prompt."""
    return "\n".join(f"- {f.key} : {f.content}" for f in facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_facts.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/facts.py tests/test_facts.py
git commit -m "feat: add Fact model and helpers for long-term memory"
```

---

### Task 2: `FactStore` — backends local et Chroma (`memory/fact_store.py`)

**Files:**
- Create: `src/velmo/memory/fact_store.py`
- Test: `tests/test_fact_store.py`

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`, `is_semantic`.
- Produces:
  - `class FactStore(Protocol)` : `write(fact: Fact) -> Fact`, `search(user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5) -> list[Fact]`, `all(user_id: str) -> list[Fact]`, `delete(user_id: str, target: str | None = None) -> int`.
  - `class LocalFactStore` (backend hors-ligne).
  - `class ChromaFactStore` (backend prod ; collection Chroma).
  - `get_fact_store() -> FactStore` (Chroma si `CHROMA_URL`, sinon local).

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_fact_store.py` :

```python
"""Unit tests for the offline fact store (LocalFactStore) and the factory."""

from __future__ import annotations

from velmo.memory.facts import Fact
from velmo.memory.fact_store import LocalFactStore, get_fact_store


def _write(store, user_id, fact_type, key, content):
    return store.write(Fact.new(user_id, fact_type, key, content))


def test_semantic_fact_replaced_on_conflict():
    # FR-009 semantic: same (fact_type, key) keeps only the most recent value.
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    _write(store, "u1", "profile", "pointure", "XL")
    pointures = [f for f in store.all("u1") if f.key == "pointure"]
    assert len(pointures) == 1
    assert pointures[0].content == "XL"


def test_semantic_update_preserves_created_at():
    store = LocalFactStore()
    first = _write(store, "u1", "profile", "pointure", "L")
    updated = _write(store, "u1", "profile", "pointure", "XL")
    assert updated.created_at == first.created_at


def test_distinct_semantic_keys_coexist():
    store = LocalFactStore()
    _write(store, "u1", "preference", "tutoiement", "oui")
    _write(store, "u1", "preference", "equipe", "OM")
    assert {f.key for f in store.all("u1")} == {"tutoiement", "equipe"}


def test_episodic_facts_accumulate():
    # FR-009 episodic: each entry is kept as a distinct record.
    store = LocalFactStore()
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    _write(store, "u1", "order_info", "order", "O-2024-0102")
    orders = [f for f in store.all("u1") if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_isolation_between_users():
    # R3: a user's read never leaks another user's facts (separate dicts).
    store = LocalFactStore()
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    _write(store, "u2", "order_info", "order", "O-2024-0101")  # same content
    u2 = store.all("u2")
    assert len(u2) == 1
    assert all(f.user_id == "u2" for f in u2)


def test_search_filters_by_fact_type():
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    got = store.search("u1", "peu importe", fact_types=["profile"])
    assert [f.key for f in got] == ["pointure"]


def test_search_respects_k():
    store = LocalFactStore()
    for i in range(7):
        _write(store, "u1", "order_info", "order", f"O-2024-000{i}")
    assert len(store.search("u1", "commande", k=3)) == 3


def test_delete_target_removes_matching_fact():
    store = LocalFactStore()
    _write(store, "u1", "profile", "adresse", "12 rue des Lilas")
    _write(store, "u1", "profile", "pointure", "L")
    removed = store.delete("u1", target="adresse")
    assert removed == 1
    assert {f.key for f in store.all("u1")} == {"pointure"}


def test_delete_all_when_target_none():
    store = LocalFactStore()
    _write(store, "u1", "profile", "adresse", "12 rue des Lilas")
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    assert store.delete("u1", target=None) == 2
    assert store.all("u1") == []


def test_delete_unknown_target_removes_nothing():
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    assert store.delete("u1", target="adresse") == 0
    assert len(store.all("u1")) == 1


def test_get_fact_store_offline_returns_local(monkeypatch):
    monkeypatch.delenv("CHROMA_URL", raising=False)
    assert isinstance(get_fact_store(), LocalFactStore)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fact_store.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.memory.fact_store'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/memory/fact_store.py` :

```python
"""FactStore: the long-term memory backend, on the kb_store pattern.

``LocalFactStore`` (a dict per user_id) is the offline/test backend; a user's
facts live in a dict another user can't reach — R3 isolation by construction.
``ChromaFactStore`` is the prod backend: a dedicated Chroma collection
(``velmo_memory``, distinct from the FAQ's ``velmo_faq``) where isolation rests on
a ``where={"user_id": …}`` filter applied in one central place. ``get_fact_store``
selects by ``CHROMA_URL``, exactly like ``get_kb()``.
"""

from __future__ import annotations

import os
from typing import Protocol
from uuid import uuid4

from .facts import Fact, is_semantic


class FactStore(Protocol):
    def write(self, fact: Fact) -> Fact: ...
    def search(
        self, user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5
    ) -> list[Fact]: ...
    def all(self, user_id: str) -> list[Fact]: ...
    def delete(self, user_id: str, target: str | None = None) -> int: ...


def _matches(fact: Fact, needle: str | None) -> bool:
    return needle is None or needle in fact.key.lower() or needle in fact.content.lower()


class LocalFactStore:
    """Offline backend: one dict of facts per user_id."""

    def __init__(self) -> None:
        self._by_user: dict[str, dict[str, Fact]] = {}

    def write(self, fact: Fact) -> Fact:
        bucket = self._by_user.setdefault(fact.user_id, {})
        if is_semantic(fact.fact_type):
            storage_key = f"{fact.fact_type}:{fact.key}"
            existing = bucket.get(storage_key)
            if existing is not None:
                fact = fact.model_copy(update={"created_at": existing.created_at})
        else:
            storage_key = f"{fact.fact_type}:{fact.key}:{uuid4().hex}"
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
            storage_key = f"{fact.fact_type}:{fact.key}"
            existing = self._collection.get(ids=[storage_key])
            metas = existing.get("metadatas") or []
            if metas:
                fact = fact.model_copy(
                    update={"created_at": metas[0].get("created_at", fact.created_at)}
                )
        else:
            storage_key = f"{fact.fact_type}:{fact.key}:{uuid4().hex}"
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
    from urllib.parse import urlparse

    parsed = urlparse(os.environ["CHROMA_URL"])
    client = chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    collection = client.get_or_create_collection("velmo_memory", embedding_function=embedder)
    return ChromaFactStore(collection)
```

> `ChromaFactStore` est le seam prod (parallèle à `ChromaKB`) : non exercé par la suite hors-ligne, activé seulement si `CHROMA_URL` est défini.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fact_store.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/fact_store.py tests/test_fact_store.py
git commit -m "feat: add FactStore (LocalFactStore offline, ChromaFactStore prod)"
```

---

### Task 3: Outils mémoire (`tools/memory_tools.py`)

**Files:**
- Create: `src/velmo/tools/memory_tools.py`
- Test: `tests/test_memory_tools.py`

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`, `render_facts`; un `FactStore` (`write`/`all`/`delete`).
- Produces:
  - `remember_fact(store, user_id: str, fact_type: str, key: str, content: str) -> dict`
  - `forget_user_data(store, user_id: str, target: str | None = None) -> dict`
  - `inspect_user_memory(store, user_id: str) -> str`

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_memory_tools.py` :

```python
"""Unit tests for the long-term memory tools."""

from __future__ import annotations

from velmo.memory.fact_store import LocalFactStore
from velmo.tools.memory_tools import (
    forget_user_data,
    inspect_user_memory,
    remember_fact,
)


def test_remember_fact_persists():
    store = LocalFactStore()
    result = remember_fact(store, "u1", "profile", "pointure", "L")
    assert result["action"] == "remembered"
    assert "pointure" in inspect_user_memory(store, "u1")


def test_forget_target_reports_count():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    result = forget_user_data(store, "u1", target="adresse")
    assert result == {"action": "forgotten", "count": 1}
    assert "Lilas" not in inspect_user_memory(store, "u1")


def test_forget_nothing_matching():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    assert forget_user_data(store, "u1", target="adresse") == {"action": "nothing_to_forget"}


def test_forget_all():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    assert forget_user_data(store, "u1", target=None) == {"action": "forgotten", "count": 2}


def test_inspect_empty_memory():
    store = LocalFactStore()
    assert "aucune information" in inspect_user_memory(store, "u1").lower()


def test_inspect_lists_all_facts():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "preference", "tutoiement", "oui")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    summary = inspect_user_memory(store, "u1")
    assert "L" in summary
    assert "tutoiement" in summary
    assert "O-2024-0101" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_tools.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.tools.memory_tools'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/tools/memory_tools.py` :

```python
"""Long-term memory tools: remember, forget (R5) and inspect (R6).

Each tool is closed over ``store``/``user_id`` by the caller — the model never
picks ``user_id`` (per-customer isolation, same discipline as the order tools).
"""

from __future__ import annotations

from ..memory.facts import Fact, render_facts
from ..memory.fact_store import FactStore


def remember_fact(
    store: FactStore, user_id: str, fact_type: str, key: str, content: str
) -> dict:
    """Store a durable fact about the customer."""
    fact = store.write(Fact.new(user_id, fact_type, key, content))
    return {"action": "remembered", "fact_type": fact.fact_type, "key": fact.key}


def forget_user_data(store: FactStore, user_id: str, target: str | None = None) -> dict:
    """Delete a targeted fact or, when ``target`` is None, every fact of the user."""
    removed = store.delete(user_id, target)
    if removed == 0:
        return {"action": "nothing_to_forget"}
    return {"action": "forgotten", "count": removed}


def inspect_user_memory(store: FactStore, user_id: str) -> str:
    """Return a human-readable French summary of everything retained (R6)."""
    facts = store.all(user_id)
    if not facts:
        return "Je n'ai aucune information mémorisée à votre sujet."
    return f"Voici ce que j'ai retenu à votre sujet :\n{render_facts(facts)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_tools.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/tools/memory_tools.py tests/test_memory_tools.py
git commit -m "feat: add remember/forget/inspect memory tools"
```

---

### Task 4: Routage déterministe des intentions mémoire (`routing.py`)

**Files:**
- Modify: `src/velmo/routing.py`
- Test: `tests/test_routing.py` (append)

**Interfaces:**
- Consumes: `velmo.tools.memory_tools.forget_user_data`, `inspect_user_memory`; un `FactStore`.
- Produces: `run_deterministic(session, user_id, kb, message, store=None) -> str | None` (nouveau paramètre `store` ; `store=None` → aucune intention mémoire routée, rétro-compatible).

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `tests/test_routing.py` :

```python
from velmo.memory.fact_store import LocalFactStore
from velmo.routing import run_deterministic
from velmo.tools.memory_tools import remember_fact


def _store_with_address():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    return store


def test_inspect_intent_routed():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert reply is not None
    assert "pointure" in reply


def test_forget_intent_asks_confirmation_first():
    store = _store_with_address()
    reply = run_deterministic(None, "u1", None, "oublie mon adresse", store)
    assert reply is not None
    assert "confirme" in reply.lower()
    # Not deleted yet.
    assert "Lilas" in run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)


def test_forget_intent_deletes_on_confirmation():
    store = _store_with_address()
    reply = run_deterministic(None, "u1", None, "oublie mon adresse, je confirme", store)
    assert "fait" in reply.lower()
    assert "Lilas" not in run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)


def test_forget_all_on_confirmation():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    reply = run_deterministic(None, "u1", None, "oublie tout, je confirme", store)
    assert "fait" in reply.lower()
    summary = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert "aucune information" in summary.lower()


def test_no_store_means_no_memory_routing():
    assert run_deterministic(None, "u1", None, "que sais-tu de moi ?", None) is None


def test_forget_unknown_target_is_gentle():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "oublie mon numéro de contrat, je confirme", store)
    assert "aucune information" in reply.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routing.py -q -k "forget or inspect or store or memory"`
Expected: FAIL (`run_deterministic` takes 4 positional args, not 5).

- [ ] **Step 3: Write the implementation**

Dans `src/velmo/routing.py`, ajouter l'import après `from . import tools` :

```python
from .tools.memory_tools import forget_user_data, inspect_user_memory
```

Ajouter, après le bloc `_FAQ_KEYWORDS`, ces constantes et helpers :

```python
_FORGET_RE = re.compile(r"\b(?:oubli|supprim|efface)\w*", re.IGNORECASE)
_INSPECT_HINTS = (
    "que sais-tu de moi",
    "que sais tu de moi",
    "quelles informations",
    "quelles infos",
    "que retiens-tu",
    "que retiens tu",
    "quelles données",
)
_GLOBAL_FORGET_HINTS = ("oublie tout", "supprime tout", "efface tout", "toutes mes", "tout ce que")


def _extract_forget_target(low: str) -> str | None:
    match = re.search(
        r"(?:oubli\w*|supprim\w*|efface\w*)\s+(?:mon|ma|mes|le|la|les|l['’])?\s*(.+)", low
    )
    if not match:
        return None
    target = match.group(1)
    for phrase in ("je confirme", "c'est confirmé", "confirme", "oui je", "vas-y"):
        target = target.replace(phrase, "")
    return target.strip(" ,.;:!?'’\"") or None


def _handle_forget(store, user_id: str, low: str, confirmed: bool) -> str:
    is_global = any(h in low for h in _GLOBAL_FORGET_HINTS)
    target = None if is_global else _extract_forget_target(low)
    label = (
        "toutes vos informations"
        if is_global
        else (f"« {target} »" if target else "cette information")
    )
    if not confirmed:
        return (
            f"Vous souhaitez que j'oublie {label} ? Cette action est irréversible. "
            "Répondez « je confirme » pour valider."
        )
    result = forget_user_data(store, user_id, target)
    if result["action"] == "nothing_to_forget":
        return "Je n'ai trouvé aucune information de ce type à oublier."
    return f"C'est fait : j'ai oublié {label} ({result['count']} élément(s) supprimé(s))."
```

Changer la signature de `run_deterministic` et insérer les intentions mémoire **juste avant** le `return None` final :

```python
def run_deterministic(session, user_id: str, kb, message: str, store=None) -> str | None:
    """Route a message to a business tool by regex. Return the reply, or None
    when no deterministic intent matches (LLM fallback)."""
    low = message.lower()
    order = ORDER_RE.search(message)
    order_id = order.group(0) if order else None
    confirmed = any(c in low for c in _CONFIRM)

    # ... (blocs commande / stock / FAQ inchangés) ...

    if store is not None and any(h in low for h in _INSPECT_HINTS):
        return inspect_user_memory(store, user_id)
    if store is not None and _FORGET_RE.search(low):
        return _handle_forget(store, user_id, low, confirmed)

    return None
```

> Le bloc mémoire est placé **après** les blocs commande/stock/FAQ et avant `return None`. Les intentions d'oubli/inspection n'ont ni numéro de commande ni mot-clé stock/FAQ : aucune collision.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routing.py -q`
Expected: PASS (tests existants + 6 nouveaux).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/routing.py tests/test_routing.py
git commit -m "feat: route forget/inspect memory intents deterministically"
```

---

### Task 5: Extracteur de faits déterministe (`memory/extract.py`)

**Files:**
- Create: `src/velmo/memory/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`; `langchain_core.messages.BaseMessage`, `HumanMessage`.
- Produces:
  - `class Extractor(Protocol)` : `extract(self, messages: list[BaseMessage]) -> list[Fact]`.
  - `class DeterministicExtractor` (constructeur `DeterministicExtractor(user_id: str)`).

> Périmètre : l'extracteur est **posé et testé unitairement** mais **pas encore branché** dans l'agent (le déclenchement automatique = ingestion R4, différé). C'est la brique offline stable derrière laquelle l'impl LangMem/LLM se substituera en prod.

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_extract.py` :

```python
"""Unit tests for the deterministic offline fact extractor."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.memory.extract import DeterministicExtractor


def _facts(text: str):
    return DeterministicExtractor("u1").extract([HumanMessage(content=text)])


def test_extracts_order_number_as_episodic():
    facts = _facts("Ma commande O-2024-0101 n'est pas arrivée.")
    assert any(f.fact_type == "order_info" and f.content == "O-2024-0101" for f in facts)


def test_extracts_tutoiement_preference():
    facts = _facts("Tu peux me tutoyer, c'est plus simple.")
    prefs = [f for f in facts if f.fact_type == "preference" and f.key == "tutoiement"]
    assert prefs and prefs[0].content == "oui"


def test_extracts_pro_status_as_profile():
    facts = _facts("Je suis client pro / revendeur.")
    profiles = [f for f in facts if f.fact_type == "profile" and f.key == "segment"]
    assert profiles and "pro" in profiles[0].content.lower()


def test_no_facts_returns_empty():
    assert _facts("Bonjour, merci beaucoup !") == []


def test_source_is_extractor():
    facts = _facts("Ma commande O-2024-0101 est en retard.")
    assert facts and all(f.source == "extractor" for f in facts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_extract.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.memory.extract'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/memory/extract.py` :

```python
"""Fact extraction from conversation.

The ``Extractor`` protocol has two implementations behind it: this deterministic
one (regex/keyword entity pinning, offline, testable) and — in a later increment
— a LangMem/LLM one for production. Wiring the extractor into automatic ingestion
(R4 overflow) is deferred; this module only defines and tests the extraction.
"""

from __future__ import annotations

import re
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage

from .facts import Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_TUTOIEMENT_HINTS = ("tutoie", "tutoyer")
_PRO_HINTS = ("client pro", "revendeur", "professionnel", "compte pro")


class Extractor(Protocol):
    def extract(self, messages: list[BaseMessage]) -> list[Fact]: ...


class DeterministicExtractor:
    """Offline entity-pinning extractor bound to one user."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def extract(self, messages: list[BaseMessage]) -> list[Fact]:
        text = " ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        low = text.lower()
        facts: list[Fact] = []

        for order_id in dict.fromkeys(_ORDER_RE.findall(text)):
            facts.append(Fact.new(self._user_id, "order_info", "order", order_id, source="extractor"))
        if any(h in low for h in _TUTOIEMENT_HINTS):
            facts.append(Fact.new(self._user_id, "preference", "tutoiement", "oui", source="extractor"))
        if any(h in low for h in _PRO_HINTS):
            facts.append(Fact.new(self._user_id, "profile", "segment", "client pro", source="extractor"))
        return facts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/extract.py tests/test_extract.py
git commit -m "feat: add deterministic offline fact extractor"
```

---

### Task 6: Intégration dans l'agent (retrieval par tour + FactStore)

**Files:**
- Modify: `src/velmo/agent_graph.py`
- Modify: `src/velmo/agent_tools.py`
- Modify: `src/velmo/agent.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent_graph.py` (append)

**Interfaces:**
- Consumes: un `FactStore` (`search`/`all`); `velmo.memory.facts.render_facts`; `velmo.memory.fact_store.get_fact_store`; `velmo.tools.memory_tools.*`.
- Produces:
  - `agent_graph.answer(..., store=None)` — injecte les faits du user dans `context`.
  - `agent_graph.build_graph(..., store=None)` — passe `store` au nœud déterministe et aux outils LLM.
  - `Agent.__init__(..., store=None)` (défaut `get_fact_store()`), `Agent.inspect_memory(user_id) -> list[Fact]`.
  - `build_tools(session, user_id, kb, store=None)` — ajoute les 3 outils mémoire quand `store` est fourni.
  - `conftest.build_reference_agent(store=None)`, `build_degraded_agent(store=None)`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `tests/test_agent_graph.py` :

```python
from velmo import agent_graph
from velmo.llm import OfflineChatModel
from velmo.memory.fact_store import LocalFactStore
from velmo.tools.memory_tools import remember_fact


def test_answer_runs_with_store_wired():
    # R2 retrieval seam: answer accepts a store and completes a turn.
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = agent_graph.answer(
        None, "u1", None, "Bonjour",
        chat_model=OfflineChatModel(), store=store,
    )
    assert isinstance(reply, str) and reply
```

> `OfflineChatModel` ne fait qu'un écho ; la preuve du rappel R2 vit dans l'acceptance (Task 7). Ici on vérifie seulement que le retrieval câblé ne casse pas le tour.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_graph.py -q -k store`
Expected: FAIL (`answer()` got an unexpected keyword argument `store`).

- [ ] **Step 3: Write the implementation**

**3a — `src/velmo/agent_graph.py`.**

Dans `build_graph`, ajouter `store=None` à la signature, passer `store` au routage et aux outils :

```python
def build_graph(
    session,
    user_id: str,
    kb,
    chat_model: BaseChatModel,
    context: str = "",
    checkpointer: BaseCheckpointSaver | None = None,
    store=None,
):
    """Compile the two-node agent graph bound to one request."""

    def deterministic_node(state: AgentState) -> dict:
        message = state["messages"][-1].content
        reply = run_deterministic(session, user_id, kb, message, store)
        if reply is None:
            return {"matched": False}
        return {"messages": [AIMessage(content=reply)], "matched": True}
```

et l'appel à `build_tools` :

```python
    react = create_agent(
        model=chat_model,
        tools=build_tools(session, user_id, kb, store),
        system_prompt=system_prompt,
    )
```

Dans `answer`, ajouter `store=None`, faire la recherche par tour avant la compilation :

```python
def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
    store=None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    if store is not None:
        from .memory.facts import render_facts

        memory = render_facts(store.search(user_id, message))
        if memory:
            context = f"{memory}\n{context}".rstrip() if context else memory
    graph = build_graph(session, user_id, kb, chat_model, context, checkpointer, store)
    config = {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)], "matched": False},
        config,
    )
    return result["messages"][-1].content
```

**3b — `src/velmo/agent_tools.py`.** Ajouter `store` et les 3 outils mémoire.

Import en tête (après `from . import tools`) :

```python
from .tools.memory_tools import (
    forget_user_data as _forget_user_data,
    inspect_user_memory as _inspect_user_memory,
    remember_fact as _remember_fact,
)
```

Changer la signature :

```python
def build_tools(session, user_id: str, kb, store=None) -> list[BaseTool]:
    """Build the per-request toolset bound to one authenticated customer."""
```

Remplacer le `return [ ... ]` final par la construction conditionnelle :

```python
    business_tools = [
        get_order,
        track_shipment,
        check_stock,
        search_kb,
        update_order_item,
        update_shipping_address,
        cancel_order,
        create_return,
        trigger_refund,
        escalate_to_human,
    ]

    if store is None:
        return business_tools

    @tool
    def remember_fact(fact_type: str, key: str, content: str) -> dict:
        """Mémorise un fait durable sur le client (préférence, profil, commande).

        Args:
            fact_type: Un de preference, profile, order_info, dispute.
            key: Attribut concerné (ex. pointure, tutoiement, order).
            content: Valeur à retenir.
        """
        return _remember_fact(store, user_id, fact_type, key, content)

    @tool
    def forget_user_data(target: str | None = None) -> dict:
        """Oublie une information du client (ou toutes si target est vide).

        Args:
            target: Mot-clé de l'information à oublier ; vide = tout oublier.
        """
        return _forget_user_data(store, user_id, target)

    @tool
    def inspect_user_memory() -> str:
        """Résume ce que l'agent a retenu sur le client (traçabilité)."""
        return _inspect_user_memory(store, user_id)

    return business_tools + [remember_fact, forget_user_data, inspect_user_memory]
```

**3c — `src/velmo/agent.py`.** Ajouter `store` et `inspect_memory`.

Import :

```python
from .memory.checkpointer import get_checkpointer
from .memory.fact_store import get_fact_store
```

`__init__` :

```python
    def __init__(
        self,
        chat_model: BaseChatModel | None,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
        checkpointer: BaseCheckpointSaver | None = None,
        store=None,
    ) -> None:
        self.chat_model = chat_model
        self.guardrails = guardrails
        self.session = session
        self.kb = kb
        self.checkpointer: BaseCheckpointSaver = checkpointer or get_checkpointer()
        self.store = store if store is not None else get_fact_store()
```

`respond` — passer `store` :

```python
        answer = agent_graph.answer(
            self.session,
            user_id,
            self.kb,
            message,
            chat_model=self.chat_model,
            checkpointer=self.checkpointer,
            thread_id=user_id,
            store=self.store,
        )
```

Ajouter, après `get_state` :

```python
    def inspect_memory(self, user_id: str):
        """Return the durable facts retained for a user (R6 traceability)."""
        return self.store.all(user_id)
```

**3d — `tests/conftest.py`.** Passer un `LocalFactStore` neuf par agent.

Import :

```python
from velmo.memory.fact_store import LocalFactStore
```

Les deux fabriques :

```python
def build_reference_agent(store=None) -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=GuardrailEngine(),
        session=seeded_session(),
        kb=LocalKB(),
        store=store if store is not None else LocalFactStore(),
    )


def build_degraded_agent(store=None) -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=AllowAllGuardrails(),
        session=seeded_session(),
        kb=LocalKB(),
        store=store if store is not None else LocalFactStore(),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_graph.py tests/test_agent.py tests/test_agent_tools.py -q`
Expected: PASS (existants + `test_answer_runs_with_store_wired`).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent_graph.py src/velmo/agent_tools.py src/velmo/agent.py tests/conftest.py tests/test_agent_graph.py
git commit -m "feat: wire the fact store into the agent (per-turn retrieval + tools)"
```

---

### Task 7: Acceptance mémoire long terme + documentation

**Files:**
- Modify: `tests/acceptance/test_memory.py` (dé-xfail R2/R3/R5, ajout R6/FR-009/FR-010)
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `conftest.build_reference_agent(store=None)`; `velmo.tools.memory_tools.remember_fact`; `velmo.memory.fact_store.LocalFactStore`.
- Produces: (aucune API — tests + docs)

- [ ] **Step 1: Rewrite the acceptance tests**

Remplacer **intégralement** `tests/acceptance/test_memory.py` par :

```python
"""Tests d'acceptance — mémoire long terme (chantier 003).

R1 (fil court terme) reste couvert via le checkpointer. R2/R3/R5/R6 s'appuient
sur le FactStore : on pilote le vrai agent et on assère sur le stocké
(`Agent.inspect_memory`) ou sur la réponse déterministe (oubli/inspection), jamais
sur l'écho du modèle offline. Tout tourne sur `LocalFactStore`, sans Docker.
"""

from __future__ import annotations

from conftest import build_reference_agent
from velmo.memory.fact_store import LocalFactStore
from velmo.tools.memory_tools import remember_fact


def test_recall_over_30_messages():
    # R1 : l'info du 1er message est restituée après 30+ messages (checkpointer).
    agent = build_reference_agent()
    user = "acc-recall"
    agent.respond(user, "Ma commande prioritaire est O-2024-0101.")
    for i in range(30):
        agent.respond(user, f"Question de suivi {i} sur un maillot.")

    contents = [m.content for m in agent.get_state(user)]
    assert any("O-2024-0101" in c for c in contents)


def test_cross_session_persistence():
    # R2 : pointure, clubs et segment retrouvés une session plus tard (même Store).
    store = LocalFactStore()
    build_reference_agent(store)  # session 1
    remember_fact(store, "acc-marc", "profile", "pointure", "L")
    remember_fact(store, "acc-marc", "profile", "clubs", "OM et Brésil")
    remember_fact(store, "acc-marc", "profile", "segment", "revendeur")

    session2 = build_reference_agent(store)  # nouvelle session, même client, même Store
    contents = " ".join(f.content for f in session2.inspect_memory("acc-marc"))
    assert "L" in contents
    assert "OM" in contents
    assert "revendeur" in contents


def test_isolation_between_customers():
    # R3 : Marc ne voit jamais les commandes de Sophie.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    remember_fact(store, "acc-marc", "order_info", "order", "O-2024-0103")
    remember_fact(store, "acc-sophie", "order_info", "order", "O-2024-0107")

    sophie = " ".join(f.content for f in agent.inspect_memory("acc-sophie"))
    assert "O-2024-0107" in sophie
    assert "O-2024-0103" not in sophie


def test_right_to_be_forgotten():
    # R5 : « oublie mon adresse » supprime effectivement l'information via l'agent.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-forget"
    remember_fact(store, user, "profile", "adresse", "12 rue des Lilas")
    assert any("Lilas" in f.content for f in agent.inspect_memory(user))

    ask = agent.respond(user, "oublie mon adresse")
    assert "confirme" in ask.lower()  # confirmation demandée, rien supprimé encore
    assert any("Lilas" in f.content for f in agent.inspect_memory(user))

    agent.respond(user, "oublie mon adresse, je confirme")
    assert not any("Lilas" in f.content for f in agent.inspect_memory(user))


def test_inspect_user_memory():
    # R6 : l'inspection restitue tous les faits actifs.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-inspect"
    remember_fact(store, user, "profile", "pointure", "L")
    remember_fact(store, user, "preference", "tutoiement", "oui")
    remember_fact(store, user, "order_info", "order", "O-2024-0101")

    summary = agent.respond(user, "que sais-tu de moi ?")
    assert "L" in summary
    assert "tutoiement" in summary
    assert "O-2024-0101" in summary


def test_semantic_conflict_keeps_latest():
    # FR-009 sémantique : une seule pointure subsiste (la plus récente).
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-conflict"
    remember_fact(store, user, "profile", "pointure", "L")
    remember_fact(store, user, "profile", "pointure", "XL")
    pointures = [f for f in agent.inspect_memory(user) if f.key == "pointure"]
    assert len(pointures) == 1
    assert pointures[0].content == "XL"


def test_episodic_facts_accumulate():
    # FR-009 épisodique : deux commandes distinctes coexistent.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-orders"
    remember_fact(store, user, "order_info", "order", "O-2024-0101")
    remember_fact(store, user, "order_info", "order", "O-2024-0102")
    orders = [f for f in agent.inspect_memory(user) if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_forget_confirmation_is_deterministic_template():
    # FR-010 : la confirmation est un gabarit littéral et stable, pas du LLM.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-fr010"
    remember_fact(store, user, "profile", "adresse", "12 rue des Lilas")
    reply = agent.respond(user, "oublie mon adresse")
    assert "irréversible" in reply.lower()
    assert "je confirme" in reply.lower()
```

- [ ] **Step 2: Run the acceptance tests**

Run: `uv run pytest tests/acceptance/test_memory.py -q`
Expected: PASS (8 tests ; les anciens xfail R2/R3/R5 sont désormais verts).

- [ ] **Step 3: Update the documentation**

Dans `CLAUDE.md`, section « Trois modules à construire », remplacer le bullet **Mémoire long terme** par :

```markdown
- **Mémoire long terme (chantier 003, fait pour R2/R3/R5/R6)** : `FactStore` sur le
  patron `kb_store` (`velmo.memory.fact_store.get_fact_store` : `LocalFactStore`
  hors-ligne, `ChromaFactStore` / collection `velmo_memory` en prod). Faits typés
  (`velmo.memory.facts.Fact`, sémantique vs épisodique, FR-009), trois outils
  (`velmo.tools.memory_tools` : `remember_fact`/`forget_user_data`/`inspect_user_memory`),
  recherche par tour injectée dans le `context` du graphe. Intentions d'oubli/inspection
  routées en déterministe (FR-010). **Différé** : extraction auto LangMem/LLM, ingestion
  « sans perte » de l'excédent (R4), async.
```

Dans `README.md`, section « Features », remplacer « Mémoire durable et isolée par client (à construire) » par :

```markdown
- Mémoire durable et isolée par client : faits durables (FactStore Chroma/local), droit à l'oubli (RGPD) et inspection
```

Et dans le « Layout » du README, mettre à jour la ligne `memory/` :

```markdown
  memory/           Mémoire court terme (checkpointer) + long terme (FactStore, faits, oubli, inspection)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest tests/ -q`
Expected: les tests mémoire (unitaires + acceptance) passent ; les échecs restants sont uniquement les pré-existants garde-fous (×5) et mlops (×3). **Plus aucun `xfail`** côté mémoire.

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_memory.py CLAUDE.md README.md
git commit -m "test: long-term memory acceptance (R2/R3/R5/R6) + docs"
```

---

## Self-Review

**1. Spec coverage :**
- R2 (faits cross-session) → Task 2 (`FactStore.write`/`all`), Task 6 (retrieval par tour → `context`), Task 7 (`test_cross_session_persistence`). ✅
- R3 (isolation) → dict par `user_id` (Task 2 `LocalFactStore`) / filtre `where` (Task 2 `ChromaFactStore`), Task 7 (`test_isolation_between_customers`, `test_isolation_between_users`). ✅
- R5 (droit à l'oubli) → `FactStore.delete` Task 2, `forget_user_data` Task 3, routage + confirmation Task 4, `test_right_to_be_forgotten` Task 7. ✅
- R6 (inspection) → `FactStore.all`/`inspect_user_memory` Tasks 2/3, `Agent.inspect_memory` Task 6, `test_inspect_user_memory` Task 7. ✅
- FR-009 sémantique/épisodique → Task 2 + acceptance Task 7. ✅
- FR-010 (gabarit déterministe) → Task 4 `_handle_forget`, `test_forget_confirmation_is_deterministic_template` Task 7. ✅
- FR-003 (filtre `fact_type`) → `search(fact_types=...)` Task 2. ✅ (classement sémantique par embedding = différé, documenté.)
- FactStore Chroma en prod, FAQ non touchée → Task 2 (`ChromaFactStore`, collection `velmo_memory`). ✅
- Extracteur (interface + impl déterministe) → Task 5. ✅
- Différé (LangMem, R4 ingestion, async, `create_retriever_tool`) → non implémenté, documenté dans Global Constraints + spec §7. ✅

**2. Placeholder scan :** aucun TBD/TODO ; chaque étape de code porte le code complet. ✅

**3. Type consistency :** `Fact(user_id, fact_type, key, content, created_at, updated_at, source)` identique partout ; `Fact.new(...)` cohérent Tasks 3/5. Méthodes `FactStore.write/search/all/delete` (Task 2) appelées à l'identique par les tools (Task 3), le routage (Task 4) et l'agent (Task 6). `run_deterministic(..., store=None)` cohérent Task 4 ↔ Task 6. `build_tools(session, user_id, kb, store=None)` cohérent Task 6. `build_reference_agent(store=None)` cohérent Tasks 6/7. ✅
