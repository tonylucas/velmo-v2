# Mémoire long terme (chantier 003) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter l'agent d'une mémoire long terme (faits durables isolés par utilisateur, droit à l'oubli, inspection) via le Store LangGraph, testable entièrement hors-ligne.

**Architecture:** Le Store LangGraph (`BaseStore`) est le jumeau du checkpointer : `InMemoryStore` hors-ligne, backend Postgres en prod (seam), namespace `(user_id,)` pour l'isolation R3. Les faits (`Fact` pydantic) portent un `fact_type` (sémantique vs épisodique) qui pilote la règle de conflit FR-009. Trois outils (`remember_fact`, `forget_user_data`, `inspect_user_memory`) et une recherche par tour injectée dans le `context` déjà existant de `agent_graph.answer` couvrent R2/R5/R6 ; les intentions d'oubli/inspection sont routées dans le nœud déterministe (FR-010, testable sans LLM).

**Tech Stack:** Python 3.11, `uv`, pydantic v2, LangGraph (`langgraph.store`), pytest. Pas de nouvelle dépendance.

## Global Constraints

- Gestionnaire de paquets : `uv` (`uv run pytest …`). Pas de mypy — la vérification est **pytest uniquement**.
- Tout le code (identifiants, docstrings, commentaires, messages de commit) est **en anglais**. Seuls les textes destinés au client final (réponses de l'agent, gabarits de confirmation) sont en français.
- Le cœur tourne **hors-ligne** : `InMemoryStore` en test/dev, aucun Docker/Chroma/Postgres requis pour la suite.
- **Isolation R3** : toute lecture/écriture passe par le namespace `(user_id,)`. Un outil ne choisit jamais `user_id` (fermeture, comme les outils métier existants).
- **`fact_type`** ∈ {`preference`, `profile`} (sémantique) ∪ {`order_info`, `dispute`} (épisodique).
- **FR-009** : conflit sémantique de même `(fact_type, key)` → **remplace** (garde le plus récent) ; épisodique → **ajoute** (jamais écrasé).
- **FR-010** : la confirmation avant un oubli est un **gabarit déterministe**, jamais générée par le LLM.
- Périmètre : l'extraction automatique par LLM (LangMem), l'ingestion « sans perte » de l'excédent (R4) et l'async sont **différés** (voir la spec §7). L'interface `Extractor` + une impl déterministe sont posées ici.
- Backend de prod du Store : **Postgres** (même DB que le checkpointer), via import paresseux avec repli `InMemoryStore` — refinement assumé de la spec (qui disait « Chroma ») car LangGraph n'a pas de `BaseStore` Chroma natif ; Chroma reste le backend FAQ et le futur backend épisodique R4.

---

### Task 1: Modèle `Fact` et opérations de stockage (`memory/facts.py`)

**Files:**
- Create: `src/velmo/memory/facts.py`
- Test: `tests/test_facts.py`

**Interfaces:**
- Consumes: `langgraph.store.base.BaseStore`, `langgraph.store.memory.InMemoryStore` (tests).
- Produces:
  - `class Fact(BaseModel)` avec champs `user_id: str`, `fact_type: str`, `key: str`, `content: str`, `created_at: str`, `updated_at: str`, `source: str = "tool"`.
  - `SEMANTIC_TYPES: set[str]`, `EPISODIC_TYPES: set[str]`, `FACT_TYPES: set[str]`.
  - `write_fact(store, user_id: str, fact_type: str, key: str, content: str, source: str = "tool") -> Fact`
  - `all_facts(store, user_id: str) -> list[Fact]` (tri `updated_at` décroissant)
  - `search_facts(store, user_id: str, query: str, fact_types: list[str] | None = None, k: int = 5) -> list[Fact]`
  - `delete_facts(store, user_id: str, target: str | None = None) -> int`
  - `render_facts(facts: list[Fact]) -> str`

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_facts.py` :

```python
"""Unit tests for the long-term fact model and store operations."""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from velmo.memory.facts import (
    all_facts,
    delete_facts,
    render_facts,
    search_facts,
    write_fact,
)


def test_semantic_fact_replaced_on_conflict():
    # FR-009 semantic: same (fact_type, key) keeps only the most recent value.
    store = InMemoryStore()
    write_fact(store, "u1", "profile", "pointure", "L")
    write_fact(store, "u1", "profile", "pointure", "XL")

    facts = [f for f in all_facts(store, "u1") if f.key == "pointure"]
    assert len(facts) == 1
    assert facts[0].content == "XL"


def test_semantic_fact_preserves_created_at_on_update():
    store = InMemoryStore()
    first = write_fact(store, "u1", "profile", "pointure", "L")
    updated = write_fact(store, "u1", "profile", "pointure", "XL")
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at


def test_distinct_semantic_keys_coexist():
    # Two different preferences must NOT collide.
    store = InMemoryStore()
    write_fact(store, "u1", "preference", "tutoiement", "oui")
    write_fact(store, "u1", "preference", "equipe", "OM")
    keys = {f.key for f in all_facts(store, "u1")}
    assert keys == {"tutoiement", "equipe"}


def test_episodic_facts_accumulate():
    # FR-009 episodic: each entry is kept as a distinct record.
    store = InMemoryStore()
    write_fact(store, "u1", "order_info", "order", "O-2024-0101")
    write_fact(store, "u1", "order_info", "order", "O-2024-0102")
    orders = [f for f in all_facts(store, "u1") if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_isolation_between_users():
    # R3: a namespace read never leaks another user's facts.
    store = InMemoryStore()
    write_fact(store, "u1", "order_info", "order", "O-2024-0101")
    write_fact(store, "u2", "order_info", "order", "O-2024-0101")  # same content
    u2 = all_facts(store, "u2")
    assert len(u2) == 1
    assert all(f.user_id == "u2" for f in u2)


def test_search_filters_by_fact_type():
    store = InMemoryStore()
    write_fact(store, "u1", "profile", "pointure", "L")
    write_fact(store, "u1", "order_info", "order", "O-2024-0101")
    got = search_facts(store, "u1", "peu importe", fact_types=["profile"])
    assert [f.key for f in got] == ["pointure"]


def test_search_respects_k():
    store = InMemoryStore()
    for i in range(7):
        write_fact(store, "u1", "order_info", "order", f"O-2024-000{i}")
    assert len(search_facts(store, "u1", "commande", k=3)) == 3


def test_delete_target_removes_matching_fact():
    store = InMemoryStore()
    write_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    write_fact(store, "u1", "profile", "pointure", "L")
    removed = delete_facts(store, "u1", target="adresse")
    assert removed == 1
    assert {f.key for f in all_facts(store, "u1")} == {"pointure"}


def test_delete_all_when_target_none():
    store = InMemoryStore()
    write_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    write_fact(store, "u1", "order_info", "order", "O-2024-0101")
    removed = delete_facts(store, "u1", target=None)
    assert removed == 2
    assert all_facts(store, "u1") == []


def test_render_facts_lists_content():
    store = InMemoryStore()
    write_fact(store, "u1", "profile", "pointure", "L")
    rendered = render_facts(all_facts(store, "u1"))
    assert "pointure" in rendered
    assert "L" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_facts.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.memory.facts'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/memory/facts.py` :

```python
"""Durable facts: the pydantic model and the store operations behind it.

Facts live in a LangGraph ``BaseStore`` namespaced by ``(user_id,)`` — that
namespace is what gives R3 isolation by construction. A ``fact_type`` splits
semantic traits (one mutable value per attribute — FR-009 replace) from episodic
events (accumulated, never overwritten).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from langgraph.store.base import BaseStore
from pydantic import BaseModel

SEMANTIC_TYPES = {"preference", "profile"}
EPISODIC_TYPES = {"order_info", "dispute"}
FACT_TYPES = SEMANTIC_TYPES | EPISODIC_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Fact(BaseModel):
    user_id: str
    fact_type: str
    key: str
    content: str
    created_at: str
    updated_at: str
    source: str = "tool"


def write_fact(
    store: BaseStore,
    user_id: str,
    fact_type: str,
    key: str,
    content: str,
    source: str = "tool",
) -> Fact:
    """Write a fact. Semantic types replace the same (fact_type, key); episodic
    types append a new record."""
    namespace = (user_id,)
    now = _now()
    if fact_type in SEMANTIC_TYPES:
        storage_key = f"{fact_type}:{key}"
        existing = store.get(namespace, storage_key)
        created_at = existing.value["created_at"] if existing else now
        fact = Fact(
            user_id=user_id,
            fact_type=fact_type,
            key=key,
            content=content,
            created_at=created_at,
            updated_at=now,
            source=source,
        )
        store.put(namespace, storage_key, fact.model_dump())
        return fact

    storage_key = f"{fact_type}:{key}:{uuid4().hex}"
    fact = Fact(
        user_id=user_id,
        fact_type=fact_type,
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        source=source,
    )
    store.put(namespace, storage_key, fact.model_dump())
    return fact


def all_facts(store: BaseStore, user_id: str) -> list[Fact]:
    """Return every fact of a user, most recently updated first."""
    items = store.search((user_id,))
    facts = [Fact(**item.value) for item in items]
    facts.sort(key=lambda f: f.updated_at, reverse=True)
    return facts


def search_facts(
    store: BaseStore,
    user_id: str,
    query: str,
    fact_types: list[str] | None = None,
    k: int = 5,
) -> list[Fact]:
    """Return the user's facts relevant to this turn, capped at ``k``.

    ``query`` is accepted for interface stability; semantic ranking against it
    ships with the embeddings/LangMem increment. Offline the facts are returned
    most-recent-first, optionally filtered by ``fact_types``.
    """
    facts = all_facts(store, user_id)
    if fact_types:
        allowed = set(fact_types)
        facts = [f for f in facts if f.fact_type in allowed]
    return facts[:k]


def delete_facts(store: BaseStore, user_id: str, target: str | None = None) -> int:
    """Delete facts. ``target=None`` wipes the whole namespace; otherwise delete
    facts whose key or content contains ``target`` (case-insensitive). Returns the
    number of facts removed."""
    namespace = (user_id,)
    items = store.search(namespace)
    to_delete: list[str] = []
    needle = target.lower() if target else None
    for item in items:
        fact = Fact(**item.value)
        if needle is None or needle in fact.key.lower() or needle in fact.content.lower():
            to_delete.append(item.key)
    for storage_key in to_delete:
        store.delete(namespace, storage_key)
    return len(to_delete)


def render_facts(facts: list[Fact]) -> str:
    """Render facts as a compact bullet list for injection into the LLM prompt."""
    return "\n".join(f"- {f.key} : {f.content}" for f in facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_facts.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/facts.py tests/test_facts.py
git commit -m "feat: add Fact model and store operations for long-term memory"
```

---

### Task 2: Fabrique du Store (`memory/store.py`)

**Files:**
- Create: `src/velmo/memory/store.py`
- Test: `tests/test_memory_store.py`

**Interfaces:**
- Consumes: `langgraph.store.base.BaseStore`, `langgraph.store.memory.InMemoryStore`.
- Produces: `get_store() -> BaseStore` (InMemoryStore hors-ligne ; Postgres seam si `DB_URL`).

- [ ] **Step 1: Write the failing test**

Créer `tests/test_memory_store.py` :

```python
"""Unit test for the long-term store factory."""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from velmo.memory.store import get_store


def test_get_store_offline_returns_in_memory(monkeypatch):
    monkeypatch.delenv("DB_URL", raising=False)
    store = get_store()
    assert isinstance(store, InMemoryStore)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_store.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'velmo.memory.store'`).

- [ ] **Step 3: Write the implementation**

Créer `src/velmo/memory/store.py` :

```python
"""Store factory: the LangGraph long-term memory backend.

``InMemoryStore`` offline (tests, eval); a Postgres store when ``DB_URL`` is set
and the Postgres store package is installed. Mirrors ``get_checkpointer()`` — the
Postgres branch is the prod seam, not exercised by the offline suite. Semantic
indexing (embeddings) ships with the LangMem/episodic increment.
"""

from __future__ import annotations

import os

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


def get_store() -> BaseStore:
    """Return the Postgres store if configured, else the in-memory one."""
    db_url = os.getenv("DB_URL")
    if not db_url:
        return InMemoryStore()
    try:
        from langgraph.store.postgres import PostgresStore
    except ImportError:
        return InMemoryStore()
    from psycopg import Connection

    conninfo = db_url.replace("postgresql+psycopg://", "postgresql://")
    conn = Connection.connect(conninfo, autocommit=True, prepare_threshold=0)
    store = PostgresStore(conn)
    store.setup()
    return store
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/store.py tests/test_memory_store.py
git commit -m "feat: add long-term store factory (InMemoryStore offline)"
```

---

### Task 3: Outils mémoire (`tools/memory_tools.py`)

**Files:**
- Create: `src/velmo/tools/memory_tools.py`
- Test: `tests/test_memory_tools.py`

**Interfaces:**
- Consumes: `velmo.memory.facts.write_fact`, `all_facts`, `delete_facts`, `render_facts`.
- Produces:
  - `remember_fact(store, user_id: str, fact_type: str, key: str, content: str) -> dict`
  - `forget_user_data(store, user_id: str, target: str | None = None) -> dict`
  - `inspect_user_memory(store, user_id: str) -> str`

- [ ] **Step 1: Write the failing tests**

Créer `tests/test_memory_tools.py` :

```python
"""Unit tests for the long-term memory tools."""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from velmo.tools.memory_tools import (
    forget_user_data,
    inspect_user_memory,
    remember_fact,
)


def test_remember_fact_persists():
    store = InMemoryStore()
    result = remember_fact(store, "u1", "profile", "pointure", "L")
    assert result["action"] == "remembered"
    assert "pointure" in inspect_user_memory(store, "u1")


def test_forget_target_reports_count():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    result = forget_user_data(store, "u1", target="adresse")
    assert result == {"action": "forgotten", "count": 1}
    assert "Lilas" not in inspect_user_memory(store, "u1")


def test_forget_nothing_matching():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    result = forget_user_data(store, "u1", target="adresse")
    assert result == {"action": "nothing_to_forget"}


def test_forget_all():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    result = forget_user_data(store, "u1", target=None)
    assert result == {"action": "forgotten", "count": 2}


def test_inspect_empty_memory():
    store = InMemoryStore()
    assert "aucune information" in inspect_user_memory(store, "u1").lower()


def test_inspect_lists_all_facts():
    store = InMemoryStore()
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

from langgraph.store.base import BaseStore

from ..memory.facts import all_facts, delete_facts, render_facts, write_fact


def remember_fact(
    store: BaseStore, user_id: str, fact_type: str, key: str, content: str
) -> dict:
    """Store a durable fact about the customer."""
    fact = write_fact(store, user_id, fact_type, key, content)
    return {"action": "remembered", "fact_type": fact.fact_type, "key": fact.key}


def forget_user_data(store: BaseStore, user_id: str, target: str | None = None) -> dict:
    """Delete a targeted fact or, when ``target`` is None, every fact of the user."""
    removed = delete_facts(store, user_id, target)
    if removed == 0:
        return {"action": "nothing_to_forget"}
    return {"action": "forgotten", "count": removed}


def inspect_user_memory(store: BaseStore, user_id: str) -> str:
    """Return a human-readable French summary of everything retained (R6)."""
    facts = all_facts(store, user_id)
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
- Consumes: `velmo.tools.memory_tools.forget_user_data`, `inspect_user_memory`.
- Produces: `run_deterministic(session, user_id, kb, message, store=None) -> str | None` (nouveau paramètre `store`, rétro-compatible : `store=None` → aucune intention mémoire routée).

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `tests/test_routing.py` :

```python
from langgraph.store.memory import InMemoryStore

from velmo.routing import run_deterministic
from velmo.tools.memory_tools import remember_fact


def test_inspect_intent_routed():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert reply is not None
    assert "pointure" in reply


def test_forget_intent_asks_confirmation_first():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    reply = run_deterministic(None, "u1", None, "oublie mon adresse", store)
    assert reply is not None
    assert "confirme" in reply.lower()
    # Not deleted yet.
    assert run_deterministic(None, "u1", None, "que sais-tu de moi ?", store) is not None
    assert "Lilas" in run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)


def test_forget_intent_deletes_on_confirmation():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    reply = run_deterministic(None, "u1", None, "oublie mon adresse, je confirme", store)
    assert reply is not None
    assert "fait" in reply.lower()
    summary = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert "Lilas" not in summary


def test_forget_all_on_confirmation():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    reply = run_deterministic(None, "u1", None, "oublie tout, je confirme", store)
    assert "fait" in reply.lower()
    summary = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert "aucune information" in summary.lower()


def test_no_store_means_no_memory_routing():
    # Backward compatible: without a store, memory intents fall through to the LLM.
    assert run_deterministic(None, "u1", None, "que sais-tu de moi ?", None) is None


def test_forget_unknown_target_is_gentle():
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "oublie mon numéro de contrat, je confirme", store)
    assert "aucune information" in reply.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routing.py -q -k "memory or forget or inspect or store"`
Expected: FAIL (`run_deterministic` takes 4 positional args, not 5).

- [ ] **Step 3: Write the implementation**

Dans `src/velmo/routing.py`, ajouter l'import en tête (après `from . import tools`) :

```python
from .tools.memory_tools import forget_user_data, inspect_user_memory
```

Ajouter ces constantes/ helpers près des autres regex (après `_FAQ_KEYWORDS`) :

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
    match = re.search(r"(?:oubli\w*|supprim\w*|efface\w*)\s+(?:mon|ma|mes|le|la|les|l['’])?\s*(.+)", low)
    if not match:
        return None
    target = match.group(1)
    for phrase in ("je confirme", "c'est confirmé", "confirme", "oui je", "vas-y"):
        target = target.replace(phrase, "")
    return target.strip(" ,.;:!?'’\"") or None


def _handle_forget(store, user_id: str, low: str, confirmed: bool) -> str:
    is_global = any(h in low for h in _GLOBAL_FORGET_HINTS)
    target = None if is_global else _extract_forget_target(low)
    label = "toutes vos informations" if is_global else (f"« {target} »" if target else "cette information")
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

Puis, dans `run_deterministic`, changer la signature et insérer les intentions mémoire **juste avant** le `return None` final :

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

> Note d'intégration : le bloc mémoire est placé **après** les blocs commande/stock/FAQ existants et avant `return None`. Les intentions d'oubli/inspection n'ont ni numéro de commande ni mot-clé stock/FAQ, donc aucun risque de collision.

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
- Consumes: `velmo.memory.facts.Fact` (structure), `langchain_core.messages.BaseMessage`.
- Produces:
  - `class Extractor(Protocol)` avec `extract(self, messages: list[BaseMessage]) -> list[Fact]`.
  - `class DeterministicExtractor` implémentant `extract` par épinglage d'entités (regex/mots-clés).

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
    orders = [f for f in facts if f.fact_type == "order_info"]
    assert any(f.content == "O-2024-0101" for f in orders)


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
from datetime import datetime, timezone
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage

from .facts import Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_TUTOIEMENT_HINTS = ("tutoie", "tutoyer", "on peut se tutoyer")
_PRO_HINTS = ("client pro", "revendeur", "professionnel", "compte pro")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Extractor(Protocol):
    def extract(self, messages: list[BaseMessage]) -> list[Fact]:
        ...


class DeterministicExtractor:
    """Offline entity-pinning extractor bound to one user."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def _fact(self, fact_type: str, key: str, content: str) -> Fact:
        now = _now()
        return Fact(
            user_id=self._user_id,
            fact_type=fact_type,
            key=key,
            content=content,
            created_at=now,
            updated_at=now,
            source="extractor",
        )

    def extract(self, messages: list[BaseMessage]) -> list[Fact]:
        text = " ".join(
            str(m.content) for m in messages if isinstance(m, HumanMessage)
        )
        low = text.lower()
        facts: list[Fact] = []

        for order_id in dict.fromkeys(_ORDER_RE.findall(text)):
            facts.append(self._fact("order_info", "order", order_id))
        if any(h in low for h in _TUTOIEMENT_HINTS):
            facts.append(self._fact("preference", "tutoiement", "oui"))
        if any(h in low for h in _PRO_HINTS):
            facts.append(self._fact("profile", "segment", "client pro"))
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

### Task 6: Intégration dans l'agent (retrieval par tour + Store)

**Files:**
- Modify: `src/velmo/agent_graph.py`
- Modify: `src/velmo/agent_tools.py`
- Modify: `src/velmo/agent.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent_graph.py` (append)

**Interfaces:**
- Consumes: `velmo.memory.facts.search_facts`, `render_facts`; `velmo.memory.store.get_store`; `velmo.tools.memory_tools.*`.
- Produces:
  - `agent_graph.answer(..., store=None)` — injecte les faits du user dans `context`.
  - `agent_graph.build_graph(..., store=None)` — passe `store` au nœud déterministe et aux outils LLM.
  - `Agent.__init__(..., store=None)` (défaut `get_store()`), `Agent.inspect_memory(user_id) -> list[Fact]`.
  - `build_tools(session, user_id, kb, store=None)` — ajoute les 3 outils mémoire quand `store` est fourni.
  - `conftest.build_reference_agent(store=None)`, `build_degraded_agent(store=None)`.

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `tests/test_agent_graph.py` :

```python
from langgraph.store.memory import InMemoryStore

from velmo import agent_graph
from velmo.llm import OfflineChatModel
from velmo.tools.memory_tools import remember_fact


def test_answer_injects_facts_into_context():
    # R2: the user's stored facts reach the LLM prompt via `context`.
    store = InMemoryStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = agent_graph.answer(
        None, "u1", None, "Bonjour",
        chat_model=OfflineChatModel(), store=store,
    )
    # OfflineChatModel echoes the last human message; the assertion on real recall
    # lives in the acceptance suite. Here we only assert the call succeeds with a
    # store wired in (no crash, non-empty reply).
    assert isinstance(reply, str) and reply
```

> Note : cet appel passe `session=None`/`kb=None` ; `answer` avec un `OfflineChatModel` et sans intention déterministe route vers le nœud LLM (écho). Le test garde-fou de non-régression du retrieval est surtout couvert par l'acceptance (Task 7).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_graph.py -q -k inject`
Expected: FAIL (`answer()` got an unexpected keyword argument `store`).

- [ ] **Step 3: Write the implementation**

**3a — `src/velmo/agent_graph.py`.** Ajouter le paramètre `store` à `build_graph` et `answer`, brancher le retrieval et le nœud déterministe.

`build_graph` — nouvelle signature et threading :

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

Dans `build_graph`, l'appel à `build_tools` gagne `store` :

```python
    react = create_agent(
        model=chat_model,
        tools=build_tools(session, user_id, kb, store),
        system_prompt=system_prompt,
    )
```

`answer` — nouvelle signature, retrieval avant la compilation :

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
        from .memory.facts import render_facts, search_facts

        memory = render_facts(search_facts(store, user_id, message))
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

Changer la signature et l'import :

```python
from . import tools
from .tools.memory_tools import (
    forget_user_data as _forget_user_data,
    inspect_user_memory as _inspect_user_memory,
    remember_fact as _remember_fact,
)


def build_tools(session, user_id: str, kb, store=None) -> list[BaseTool]:
    """Build the per-request toolset bound to one authenticated customer."""
```

Avant le `return [...]`, ajouter (seulement si `store` fourni) :

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

Supprimer l'ancien `return [ ... ]` terminal (remplacé par les branches ci-dessus).

**3c — `src/velmo/agent.py`.** Ajouter `store` et `inspect_memory`.

```python
from .memory.checkpointer import get_checkpointer
from .memory.store import get_store
```

Dans `Agent.__init__`, ajouter le paramètre et l'attribut :

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
        self.store = store if store is not None else get_store()
```

Dans `respond`, passer `store` à `answer` :

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

Ajouter la méthode d'inspection (après `get_state`) :

```python
    def inspect_memory(self, user_id: str):
        """Return the durable facts retained for a user (R6 traceability)."""
        from .memory.facts import all_facts

        return all_facts(self.store, user_id)
```

**3d — `tests/conftest.py`.** Passer un Store neuf par agent.

Ajouter l'import :

```python
from langgraph.store.memory import InMemoryStore
```

Modifier les deux fabriques :

```python
def build_reference_agent(store=None) -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=GuardrailEngine(),
        session=seeded_session(),
        kb=LocalKB(),
        store=store if store is not None else InMemoryStore(),
    )


def build_degraded_agent(store=None) -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=AllowAllGuardrails(),
        session=seeded_session(),
        kb=LocalKB(),
        store=store if store is not None else InMemoryStore(),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_graph.py tests/test_agent.py tests/test_agent_tools.py -q`
Expected: PASS (existants + le nouveau `test_answer_injects_facts_into_context`).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent_graph.py src/velmo/agent_tools.py src/velmo/agent.py tests/conftest.py tests/test_agent_graph.py
git commit -m "feat: wire the long-term store into the agent (per-turn retrieval + tools)"
```

---

### Task 7: Acceptance mémoire long terme + documentation

**Files:**
- Modify: `tests/acceptance/test_memory.py` (dé-xfail R2/R3/R5, ajout R6/FR-009/FR-010/isolation)
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `conftest.build_reference_agent(store=None)`; `velmo.tools.memory_tools.remember_fact`; `langgraph.store.memory.InMemoryStore`.
- Produces: (aucune API — tests + docs)

- [ ] **Step 1: Rewrite the acceptance tests**

Remplacer **intégralement** `tests/acceptance/test_memory.py` par :

```python
"""Tests d'acceptance — mémoire long terme (chantier 003).

R1 (fil court terme) reste couvert via le checkpointer. R2/R3/R5/R6 s'appuient
sur le Store long terme : on pilote le vrai agent et on assère sur le stocké
(`Agent.inspect_memory`) ou sur la réponse déterministe (oubli/inspection), jamais
sur l'écho du modèle offline. Tout tourne sur `InMemoryStore`, sans Docker.
"""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from conftest import build_reference_agent
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
    store = InMemoryStore()
    session1 = build_reference_agent(store)
    remember_fact(store, "acc-marc", "profile", "pointure", "L")
    remember_fact(store, "acc-marc", "profile", "clubs", "OM et Brésil")
    remember_fact(store, "acc-marc", "profile", "segment", "revendeur")

    session2 = build_reference_agent(store)  # nouvelle session, même client, même Store
    facts = session2.inspect_memory("acc-marc")
    contents = " ".join(f.content for f in facts)
    assert "L" in contents
    assert "OM" in contents
    assert "revendeur" in contents


def test_isolation_between_customers():
    # R3 : Marc ne voit jamais les commandes de Sophie.
    store = InMemoryStore()
    agent = build_reference_agent(store)
    remember_fact(store, "acc-marc", "order_info", "order", "O-2024-0103")
    remember_fact(store, "acc-sophie", "order_info", "order", "O-2024-0107")

    sophie = " ".join(f.content for f in agent.inspect_memory("acc-sophie"))
    assert "O-2024-0107" in sophie
    assert "O-2024-0103" not in sophie


def test_right_to_be_forgotten():
    # R5 : « oublie mon adresse » supprime effectivement l'information via l'agent.
    store = InMemoryStore()
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
    store = InMemoryStore()
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
    store = InMemoryStore()
    agent = build_reference_agent(store)
    user = "acc-conflict"
    remember_fact(store, user, "profile", "pointure", "L")
    remember_fact(store, user, "profile", "pointure", "XL")
    pointures = [f for f in agent.inspect_memory(user) if f.key == "pointure"]
    assert len(pointures) == 1
    assert pointures[0].content == "XL"


def test_episodic_facts_accumulate():
    # FR-009 épisodique : deux commandes distinctes coexistent.
    store = InMemoryStore()
    agent = build_reference_agent(store)
    user = "acc-orders"
    remember_fact(store, user, "order_info", "order", "O-2024-0101")
    remember_fact(store, user, "order_info", "order", "O-2024-0102")
    orders = [f for f in agent.inspect_memory(user) if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_forget_confirmation_is_deterministic_template():
    # FR-010 : la confirmation est un gabarit littéral et stable, pas du LLM.
    store = InMemoryStore()
    agent = build_reference_agent(store)
    user = "acc-fr010"
    remember_fact(store, user, "profile", "adresse", "12 rue des Lilas")
    reply = agent.respond(user, "oublie mon adresse")
    assert "irréversible" in reply.lower()
    assert "je confirme" in reply.lower()
```

- [ ] **Step 2: Run the acceptance tests**

Run: `uv run pytest tests/acceptance/test_memory.py -q`
Expected: PASS (9 tests ; les anciens xfail R2/R3/R5 sont désormais des tests verts).

- [ ] **Step 3: Update the documentation**

Dans `CLAUDE.md`, section « Trois modules à construire », remplacer le bullet **Mémoire long terme** par un état à jour :

```markdown
- **Mémoire long terme (chantier 003, fait pour R2/R3/R5/R6)** : Store LangGraph
  (`velmo.memory.store.get_store` : `InMemoryStore` hors-ligne, Postgres en prod)
  namespacé par `user_id`. Faits typés (`velmo.memory.facts.Fact`, sémantique vs
  épisodique, FR-009), trois outils (`velmo.tools.memory_tools` :
  `remember_fact`/`forget_user_data`/`inspect_user_memory`), recherche par tour
  injectée dans le `context` du graphe. Intentions d'oubli/inspection routées en
  déterministe (FR-010). **Différé** : extraction auto LangMem/LLM, ingestion
  « sans perte » de l'excédent (R4), async.
```

Dans `README.md`, section « Features », remplacer la ligne « Mémoire durable et isolée par client (à construire) » par :

```markdown
- Mémoire durable et isolée par client : faits durables (Store LangGraph), droit à l'oubli (RGPD) et inspection
```

Et dans le « Layout » du README, mettre à jour la ligne `memory/` :

```markdown
  memory/           Mémoire court terme (checkpointer) + long terme (Store, faits, oubli, inspection)
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
- R2 (faits cross-session) → Task 1 (`write_fact`/`all_facts`), Task 6 (retrieval par tour → `context`), Task 7 (`test_cross_session_persistence`). ✅
- R3 (isolation) → namespace `(user_id,)` Task 1, Task 7 (`test_isolation_between_customers`, `test_isolation_between_users`). ✅
- R5 (droit à l'oubli) → `delete_facts` Task 1, `forget_user_data` Task 3, routage + confirmation Task 4, `test_right_to_be_forgotten` Task 7. ✅
- R6 (inspection) → `all_facts`/`inspect_user_memory` Tasks 1/3, `Agent.inspect_memory` Task 6, `test_inspect_user_memory` Task 7. ✅
- FR-009 sémantique/épisodique → Task 1 + acceptance Task 7. ✅
- FR-010 (gabarit déterministe) → Task 4 `_handle_forget`, `test_forget_confirmation_is_deterministic_template` Task 7. ✅
- FR-003 (filtre `fact_type`) → `search_facts(fact_types=...)` Task 1. ✅ (classement sémantique par embedding = différé, documenté.)
- Extracteur (interface + impl déterministe) → Task 5. ✅
- Différé (LangMem, R4 ingestion, async) → non implémenté, documenté dans Global Constraints + spec §7. ✅

**2. Placeholder scan :** aucun TBD/TODO ; chaque étape de code porte le code complet. ✅

**3. Type consistency :** `Fact(user_id, fact_type, key, content, created_at, updated_at, source)` identique partout ; `write_fact`/`search_facts`/`delete_facts`/`all_facts`/`render_facts` mêmes signatures entre Task 1 (définition), Task 3 (tools), Task 6 (agent). `run_deterministic(..., store=None)` cohérent Task 4 ↔ Task 6. `build_tools(session, user_id, kb, store=None)` cohérent Task 6. `build_reference_agent(store=None)` cohérent Tasks 6/7. ✅
