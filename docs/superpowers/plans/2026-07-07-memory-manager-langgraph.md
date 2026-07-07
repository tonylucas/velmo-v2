# MemoryManager (LangGraph + Chroma) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `MemoryManager` (`src/velmo/memory/`) so it satisfies R1–R6 (fenêtre courte + faits durables + droit à l'oubli + traçabilité), backed by a LangGraph checkpointer and ChromaDB, per `docs/superpowers/specs/2026-07-06-agent-runtime-langgraph-design.md`.

**Architecture:** Short-term window (R1/R4) lives in a one-node LangGraph `StateGraph(MessagesState)` compiled with a checkpointer (`PostgresSaver` sync if `DB_URL` set, else a process-shared `InMemorySaver`), keyed by `thread_id = user_id`. Durable facts (R2/R3/R5/R6) live in a Chroma collection (`HttpClient` if `CHROMA_URL` set, else `EphemeralClient`), isolated by `user_id` metadata, with exact `where=` filters for deletion/inspection. `Agent.respond()` stays synchronous throughout.

**Tech Stack:** Python 3.11, LangGraph (`langgraph`, `langgraph-checkpoint-postgres`), LangChain core (`langchain-core`, already present), ChromaDB (`chromadb`), SQLAlchemy/psycopg (already present), pytest.

## Global Constraints

- `Agent.respond(self, user_id: str, message: str) -> str` stays synchronous — never `async def`, never `.ainvoke()`. (`Evaluable` protocol, `src/velmo/mlops/__init__.py`, is a stable public surface.)
- Default short-term window threshold: **30 messages** (configurable), per spec 001 FR-001/FR-006.
- Isolation is strict by `user_id` everywhere (R3) — every Chroma call includes a `user_id` filter; every checkpoint call uses `thread_id = user_id`.
- No SQL table for durable facts. Chroma is the only store for R2/R5/R6, per the design doc and `docs/reco_expert.md` (corrected).
- Chroma deletion/inspection uses exact metadata `where=` filters only — never rely on similarity search for R5/R6.
- Backend selection is environment-driven with an offline default (no `DB_URL`/`CHROMA_URL` required to run tests), mirroring `src/velmo/llm.py` (`EchoLLM`/`AzureLLM`) and `src/velmo/db.py` (`fresh_sqlite_session`).
- Do not modify `tests/acceptance/test_memory.py` or `tests/conftest.py` — they are the fixed contract this plan must satisfy.
- Line length 100 (ruff), `from __future__ import annotations` at the top of every new module, French docstrings/comments matching the existing codebase style.

---

## File Structure

- **Create:** `src/velmo/memory/checkpoint.py` — short-term window: checkpointer selection, one-node history graph, append/read/remove helpers.
- **Create:** `src/velmo/memory/facts.py` — durable facts: Chroma client/collection selection, remember/store/search/list/delete helpers.
- **Modify:** `src/velmo/memory/__init__.py` — `MemoryManager` rewritten on top of the two modules above; `MemoryContext`/`Turn` unchanged.
- **Modify:** `src/velmo/agent.py` — fix the discarded-context bug: `Agent.respond()`/`Agent._handle()` must pass the rendered `MemoryContext` into the fallback LLM call.
- **Create:** `tests/unit/test_memory_checkpoint.py` — unit tests for the checkpoint module.
- **Create:** `tests/unit/test_memory_facts.py` — unit tests for the facts module.
- **Create:** `tests/unit/test_agent_memory_wiring.py` — regression test for the context-wiring fix.

---

### Task 1: Short-term window backend (`checkpoint.py`)

**Files:**
- Create: `src/velmo/memory/checkpoint.py`
- Test: `tests/unit/test_memory_checkpoint.py`

**Interfaces:**
- Produces: `build_checkpointer(db_url: str | None = None) -> BaseCheckpointSaver`, `build_history_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph`, `append_turn(graph: CompiledStateGraph, user_id: str, user_message: str, assistant_message: str) -> None`, `get_history(graph: CompiledStateGraph, user_id: str) -> list[BaseMessage]`, `remove_messages(graph: CompiledStateGraph, user_id: str, message_ids: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_memory_checkpoint.py`:

```python
"""Tests unitaires — fenêtre courte (src/velmo/memory/checkpoint.py)."""

from __future__ import annotations

from velmo.memory import checkpoint


def test_append_and_read_history():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-1", "bonjour", "salut")
    history = checkpoint.get_history(graph, "unit-user-1")
    assert [(m.type, m.content) for m in history] == [("human", "bonjour"), ("ai", "salut")]


def test_history_isolated_by_user():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-a", "msg a", "reponse a")
    checkpoint.append_turn(graph, "unit-user-b", "msg b", "reponse b")
    assert [m.content for m in checkpoint.get_history(graph, "unit-user-a")] == ["msg a", "reponse a"]
    assert [m.content for m in checkpoint.get_history(graph, "unit-user-b")] == ["msg b", "reponse b"]


def test_remove_messages_by_id():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-remove", "a supprimer", "reponse")
    history = checkpoint.get_history(graph, "unit-user-remove")
    target_id = history[0].id
    checkpoint.remove_messages(graph, "unit-user-remove", [target_id])
    remaining = checkpoint.get_history(graph, "unit-user-remove")
    assert [m.content for m in remaining] == ["reponse"]


def test_empty_history_for_unknown_user():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    assert checkpoint.get_history(graph, "unit-user-never-seen") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_memory_checkpoint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'velmo.memory.checkpoint'` (or `ImportError`).

- [ ] **Step 3: Write the implementation**

Create `src/velmo/memory/checkpoint.py`:

```python
"""Fenêtre courte de conversation : checkpointer LangGraph, isolation par `thread_id=user_id`.

Postgres (`DB_URL`) en prod ; repli mémoire partagé au niveau module hors-ligne
(tests/CI, pas de service externe) — même pattern que `llm.py`/`db.py`.

Le graphe est un unique nœud passthrough : son seul rôle est d'accumuler les
messages dans le state (réducteur `add_messages` de `MessagesState`), persistés
par le checkpointer choisi. Lire/écrire l'historique passe toujours par
`graph.invoke()`/`graph.get_state()` — jamais de `Checkpoint` construit à la main.
"""

from __future__ import annotations

import os
import threading

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

_offline_lock = threading.Lock()
_offline_saver: InMemorySaver | None = None


def _shared_offline_saver() -> InMemorySaver:
    """Checkpointer en mémoire partagé par tout le process (hors-ligne/tests).

    Une seule instance pour tout le process : deux `MemoryManager()` construits
    séparément doivent voir le même historique tant qu'aucun `DB_URL` n'est
    configuré.
    """
    global _offline_saver
    with _offline_lock:
        if _offline_saver is None:
            _offline_saver = InMemorySaver()
        return _offline_saver


def build_checkpointer(db_url: str | None = None) -> BaseCheckpointSaver:
    """Postgres si `db_url`/`DB_URL` configuré, sinon repli mémoire partagé."""
    url = db_url or os.getenv("DB_URL")
    if not url:
        return _shared_offline_saver()

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


def _passthrough(state: MessagesState) -> dict:
    return {}


def build_history_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """Graphe à un seul nœud : accumule les messages, persistés par `checkpointer`."""
    graph = StateGraph(MessagesState)
    graph.add_node("passthrough", _passthrough)
    graph.add_edge(START, "passthrough")
    graph.add_edge("passthrough", END)
    return graph.compile(checkpointer=checkpointer)


def _config(user_id: str) -> dict:
    return {"configurable": {"thread_id": user_id}}


def append_turn(
    graph: CompiledStateGraph, user_id: str, user_message: str, assistant_message: str
) -> None:
    """Ajoute un tour (message utilisateur + réponse) à l'historique persistant."""
    graph.invoke(
        {"messages": [HumanMessage(content=user_message), AIMessage(content=assistant_message)]},
        config=_config(user_id),
    )


def get_history(graph: CompiledStateGraph, user_id: str) -> list[BaseMessage]:
    """Historique complet actuel (fenêtre courte), le plus ancien en premier."""
    state = graph.get_state(_config(user_id))
    if not state.values:
        return []
    return list(state.values.get("messages", []))


def remove_messages(graph: CompiledStateGraph, user_id: str, message_ids: list[str]) -> None:
    """Supprime des messages précis de l'historique (par id) — R4 (troncature) et R5 (oubli)."""
    if not message_ids:
        return
    graph.update_state(
        _config(user_id), {"messages": [RemoveMessage(id=mid) for mid in message_ids]}
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_memory_checkpoint.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/checkpoint.py tests/unit/test_memory_checkpoint.py
git commit -m "feat(memory): add LangGraph checkpointer backend for short-term window"
```

---

### Task 2: Durable facts backend (`facts.py`)

**Files:**
- Create: `src/velmo/memory/facts.py`
- Test: `tests/unit/test_memory_facts.py`

**Interfaces:**
- Produces: `get_collection(chroma_url: str | None = None)`, `remember(collection, user_id: str, key: str, value: str) -> None`, `store_excerpt(collection, user_id: str, text: str) -> None`, `search(collection, user_id: str, query: str, k: int = 5) -> list[str]`, `all_facts(collection, user_id: str) -> list[dict]`, `delete_matching(collection, user_id: str, target: str) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_memory_facts.py`:

```python
"""Tests unitaires — faits durables (src/velmo/memory/facts.py)."""

from __future__ import annotations

from velmo.memory import facts


def test_remember_and_search():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-1", "pointure", "L")
    hits = facts.search(collection, "unit-facts-1", "Quelle est ma pointure ?")
    assert any("pointure: L" in hit for hit in hits)


def test_remember_replaces_previous_value_for_same_key():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-2", "pointure", "M")
    facts.remember(collection, "unit-facts-2", "pointure", "XL")
    stored = facts.all_facts(collection, "unit-facts-2")
    pointure_values = [f["content"] for f in stored if f.get("key") == "pointure"]
    assert pointure_values == ["pointure: XL"]


def test_search_isolated_by_user():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-a", "commande", "O-2024-0001")
    facts.remember(collection, "unit-facts-b", "commande", "O-2024-0002")
    hits_a = facts.search(collection, "unit-facts-a", "commande")
    assert any("O-2024-0001" in h for h in hits_a)
    assert not any("O-2024-0002" in h for h in hits_a)


def test_delete_matching_removes_and_counts():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-forget", "adresse", "12 rue des Lilas")
    removed = facts.delete_matching(collection, "unit-facts-forget", "adresse")
    assert removed == 1
    assert facts.all_facts(collection, "unit-facts-forget") == []


def test_store_excerpt_is_searchable():
    collection = facts.get_collection()
    facts.store_excerpt(collection, "unit-facts-excerpt", "human: Ma commande prioritaire est O-2024-0101.")
    hits = facts.search(collection, "unit-facts-excerpt", "Quelle etait ma commande prioritaire ?")
    assert any("O-2024-0101" in h for h in hits)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_memory_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'velmo.memory.facts'`.

- [ ] **Step 3: Write the implementation**

Create `src/velmo/memory/facts.py`:

```python
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
from urllib.parse import urlparse

_COLLECTION_NAME = "velmo_memory_facts"


def _client(chroma_url: str | None = None):
    import chromadb

    url = chroma_url or os.getenv("CHROMA_URL")
    if not url:
        return chromadb.EphemeralClient()
    parsed = urlparse(url)
    return chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)


def _embedding_function(chroma_url: str | None = None):
    if not (chroma_url or os.getenv("CHROMA_URL")):
        return None  # embedder par défaut de Chroma (léger, hors-ligne)
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )


def get_collection(chroma_url: str | None = None):
    """Collection Chroma des faits durables (créée si absente)."""
    client = _client(chroma_url)
    kwargs = {}
    embedding_function = _embedding_function(chroma_url)
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(_COLLECTION_NAME, **kwargs)


def remember(collection, user_id: str, key: str, value: str) -> None:
    """Enregistre un fait durable ; remplace toute version précédente du même `key` (FR-009)."""
    collection.delete(where={"$and": [{"user_id": user_id}, {"key": key}]})
    collection.upsert(
        ids=[f"{user_id}:{key}:{uuid.uuid4().hex[:8]}"],
        documents=[f"{key}: {value}"],
        metadatas=[{"user_id": user_id, "fact_type": "preference", "key": key}],
    )


def store_excerpt(collection, user_id: str, text: str) -> None:
    """Stocke un extrait de fenêtre courte évincé, tel quel (R4 : transfert vers le long terme)."""
    collection.upsert(
        ids=[f"{user_id}:excerpt:{uuid.uuid4().hex}"],
        documents=[text],
        metadatas=[{"user_id": user_id, "fact_type": "episodic_excerpt", "key": ""}],
    )


def search(collection, user_id: str, query: str, k: int = 5) -> list[str]:
    """Recherche sémantique des faits/extraits pertinents pour cet utilisateur."""
    result = collection.query(query_texts=[query], n_results=k, where={"user_id": user_id})
    return list(result.get("documents", [[]])[0])


def all_facts(collection, user_id: str) -> list[dict]:
    """Tous les faits d'un utilisateur (traçabilité, R6)."""
    got = collection.get(where={"user_id": user_id})
    return [
        {"id": id_, "content": doc, **(meta or {})}
        for id_, doc, meta in zip(got["ids"], got["documents"], got["metadatas"])
    ]


def delete_matching(collection, user_id: str, target: str) -> int:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_memory_facts.py -v`
Expected: PASS (5 tests). First run may print an ONNX model download progress bar (Chroma's default embedder, cached afterwards) — this is expected, not a failure.

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/facts.py tests/unit/test_memory_facts.py
git commit -m "feat(memory): add Chroma backend for durable facts"
```

---

### Task 3: `MemoryManager.read`/`write` (R1/R2/R3/R4)

**Files:**
- Modify: `src/velmo/memory/__init__.py`
- Test: `tests/acceptance/test_memory.py` (existing, unmodified)

**Interfaces:**
- Consumes: `checkpoint.build_checkpointer`, `checkpoint.build_history_graph`, `checkpoint.append_turn`, `checkpoint.get_history`, `checkpoint.remove_messages` (Task 1); `facts.get_collection`, `facts.remember`, `facts.store_excerpt`, `facts.search`, `facts.all_facts`, `facts.delete_matching` (Task 2).
- Produces: `MemoryManager(db_url: str | None = None, chroma_url: str | None = None, window_size: int = 30)`, `.read(user_id: str, message: str) -> MemoryContext`, `.write(user_id: str, user_message: str, assistant_message: str) -> None`, `.remember_fact(user_id: str, key: str, value: str) -> None`. `MemoryContext`/`Turn` unchanged from the current stub.

- [ ] **Step 1: Confirm the existing tests currently fail**

Run: `uv run pytest tests/acceptance/test_memory.py -v`
Expected: FAIL — `test_recall_over_30_turns`, `test_cross_session_persistence`, `test_isolation_between_customers`, `test_right_to_be_forgotten` all fail (current stub returns empty context / no-ops).

- [ ] **Step 2: Rewrite `src/velmo/memory/__init__.py`**

Replace its full content with:

```python
"""Mémoire de l'agent Velmo : fenêtre courte (checkpointer LangGraph) et faits
durables (Chroma), isolées par utilisateur.

Surface publique stable consommée par l'agent et la suite d'acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import checkpoint, facts

Turn = tuple[str, str]  # (role, content)

DEFAULT_WINDOW_SIZE = 30


@dataclass
class MemoryContext:
    """Contexte mémoire restitué pour une requête utilisateur."""

    history: list[Turn] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    episodic: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Sérialise le contexte en texte (injectable dans un prompt)."""
        parts: list[str] = []
        for role, content in self.history:
            parts.append(f"{role}: {content}")
        for key, value in self.facts.items():
            parts.append(f"fact:{key}={value}")
        parts.extend(self.episodic)
        return "\n".join(parts)


class MemoryManager:
    """Orchestre la mémoire court terme et long terme, isolée par utilisateur."""

    def __init__(
        self,
        *,
        db_url: str | None = None,
        chroma_url: str | None = None,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> None:
        self._graph = checkpoint.build_history_graph(checkpoint.build_checkpointer(db_url))
        self._collection = facts.get_collection(chroma_url)
        self._window_size = window_size

    def read(self, user_id: str, message: str) -> MemoryContext:
        """Reconstitue le contexte mémoire pertinent pour `message`."""
        history_messages = checkpoint.get_history(self._graph, user_id)
        history = [(m.type, m.content) for m in history_messages]
        episodic = facts.search(self._collection, user_id, message)
        return MemoryContext(history=history, episodic=episodic)

    def write(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """Met à jour la mémoire à partir d'un échange."""
        checkpoint.append_turn(self._graph, user_id, user_message, assistant_message)
        self._enforce_window(user_id)

    def _enforce_window(self, user_id: str) -> None:
        """R4 : au-delà du seuil, transfère les messages les plus anciens vers Chroma."""
        messages = checkpoint.get_history(self._graph, user_id)
        overflow = len(messages) - self._window_size
        if overflow <= 0:
            return
        evicted = messages[:overflow]
        for evicted_message in evicted:
            facts.store_excerpt(
                self._collection, user_id, f"{evicted_message.type}: {evicted_message.content}"
            )
        checkpoint.remove_messages(self._graph, user_id, [m.id for m in evicted])

    def remember_fact(self, user_id: str, key: str, value: str) -> None:
        """Persiste un fait durable sur l'utilisateur."""
        facts.remember(self._collection, user_id, key, value)

    def forget(self, user_id: str, target: str) -> int:
        """Supprime les souvenirs correspondant à `target`. Renvoie le nombre supprimé."""
        return 0

    def inspect(self, user_id: str) -> dict:
        """Renvoie l'état mémoire d'un utilisateur (faits + souvenirs épisodiques)."""
        return {"facts": {}, "episodic": []}
```

(`forget`/`inspect` are implemented in Tasks 4 and 5 — left as the original stub for now so this task stays focused.)

- [ ] **Step 3: Run the acceptance tests for R1/R2/R3**

Run: `uv run pytest tests/acceptance/test_memory.py::test_recall_over_30_turns tests/acceptance/test_memory.py::test_cross_session_persistence tests/acceptance/test_memory.py::test_isolation_between_customers -v`
Expected: PASS (3 tests). `test_right_to_be_forgotten` still fails — expected, handled in Task 4.

- [ ] **Step 4: Commit**

```bash
git add src/velmo/memory/__init__.py
git commit -m "feat(memory): implement MemoryManager.read/write on checkpoint+facts backends"
```

---

### Task 4: `MemoryManager.forget` (R5 — dual-store purge)

**Files:**
- Modify: `src/velmo/memory/__init__.py`
- Test: `tests/acceptance/test_memory.py::test_right_to_be_forgotten` (existing, unmodified)

**Interfaces:**
- Consumes: `checkpoint.get_history`, `checkpoint.remove_messages` (Task 1); `facts.delete_matching` (Task 2).
- Produces: `.forget(user_id: str, target: str) -> int` — purges both the short-term window and the durable facts store.

- [ ] **Step 1: Confirm the test currently fails**

Run: `uv run pytest tests/acceptance/test_memory.py::test_right_to_be_forgotten -v`
Expected: FAIL (`forget` stub returns 0, information still present).

- [ ] **Step 2: Implement `forget`**

In `src/velmo/memory/__init__.py`, replace:

```python
    def forget(self, user_id: str, target: str) -> int:
        """Supprime les souvenirs correspondant à `target`. Renvoie le nombre supprimé."""
        return 0
```

with:

```python
    def forget(self, user_id: str, target: str) -> int:
        """Supprime les souvenirs correspondant à `target`. Renvoie le nombre supprimé.

        Purge à la fois la fenêtre courte (checkpointer) et les faits durables
        (Chroma) : l'information ciblée peut se trouver dans l'une, l'autre, ou
        les deux (cf. docs/superpowers/specs/2026-07-06-agent-runtime-langgraph-design.md).
        """
        removed = facts.delete_matching(self._collection, user_id, target)

        target_low = target.lower()
        messages = checkpoint.get_history(self._graph, user_id)
        matching = [m for m in messages if target_low in m.content.lower()]
        if matching:
            checkpoint.remove_messages(self._graph, user_id, [m.id for m in matching])
            removed += len(matching)

        return removed
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `uv run pytest tests/acceptance/test_memory.py -v`
Expected: PASS — all 4 tests in `test_memory.py` now pass.

- [ ] **Step 4: Commit**

```bash
git add src/velmo/memory/__init__.py
git commit -m "feat(memory): implement forget() across short-term window and durable facts"
```

---

### Task 5: `MemoryManager.inspect` (R6 — traçabilité)

**Files:**
- Modify: `src/velmo/memory/__init__.py`
- Test: `tests/unit/test_memory_inspect.py`

**Interfaces:**
- Consumes: `facts.all_facts` (Task 2).
- Produces: `.inspect(user_id: str) -> dict` with keys `"facts"` (dict of `key -> content` for entries that have a `key`) and `"episodic"` (list of raw content strings for entries without a `key`, i.e. transferred excerpts).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_memory_inspect.py`:

```python
"""Test unitaire — traçabilité de la mémoire (R6)."""

from __future__ import annotations

from velmo.memory import MemoryManager


def test_inspect_lists_facts_and_episodic_entries():
    mm = MemoryManager()
    user = "unit-inspect"
    mm.remember_fact(user, "pointure", "L")
    mm.remember_fact(user, "clubs", "OM et Bresil")

    result = mm.inspect(user)
    assert result["facts"]["pointure"] == "pointure: L"
    assert result["facts"]["clubs"] == "clubs: OM et Bresil"


def test_inspect_omits_forgotten_facts():
    mm = MemoryManager()
    user = "unit-inspect-forget"
    mm.remember_fact(user, "adresse", "12 rue des Lilas")
    mm.forget(user, "adresse")

    result = mm.inspect(user)
    assert "adresse" not in result["facts"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_memory_inspect.py -v`
Expected: FAIL (`inspect` stub returns `{"facts": {}, "episodic": []}` always).

- [ ] **Step 3: Implement `inspect`**

In `src/velmo/memory/__init__.py`, replace:

```python
    def inspect(self, user_id: str) -> dict:
        """Renvoie l'état mémoire d'un utilisateur (faits + souvenirs épisodiques)."""
        return {"facts": {}, "episodic": []}
```

with:

```python
    def inspect(self, user_id: str) -> dict:
        """Renvoie l'état mémoire d'un utilisateur (faits + souvenirs épisodiques)."""
        entries = facts.all_facts(self._collection, user_id)
        facts_by_key = {e["key"]: e["content"] for e in entries if e.get("key")}
        episodic = [e["content"] for e in entries if not e.get("key")]
        return {"facts": facts_by_key, "episodic": episodic}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_memory_inspect.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/__init__.py tests/unit/test_memory_inspect.py
git commit -m "feat(memory): implement inspect() for memory traceability (R6)"
```

---

### Task 6: Fix the discarded memory-context bug in `Agent`

**Files:**
- Modify: `src/velmo/agent.py:70-138` (`respond`, `_handle`)
- Test: `tests/unit/test_agent_memory_wiring.py`

**Interfaces:**
- Consumes: `MemoryManager.read` (Task 3), returning a `MemoryContext` with `.render() -> str`.
- Produces: `Agent.respond(self, user_id: str, message: str) -> str` (signature unchanged); `Agent._handle(self, user_id: str, message: str, context: MemoryContext) -> str` (new `context` parameter).

**Context:** Today, `Agent.respond()` calls `self.memory.read(user_id, message)` and discards the result; `_handle()`'s final fallback line calls `self.llm.invoke(SYSTEM_PROMPT, "", message)` with a hardcoded empty context. This means memory (R1) never actually reaches the LLM for free-form messages. `EchoLLM` (used in tests/CI) ignores its `context` argument, so no existing test currently catches this bug — a new regression test is required.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_agent_memory_wiring.py`:

```python
"""Test unitaire — le contexte mémoire doit atteindre l'appel LLM du fallback."""

from __future__ import annotations

from velmo.agent import Agent
from velmo.guardrails import GuardrailEngine
from velmo.memory import MemoryManager


class RecordingLLM:
    """Faux LLM qui mémorise le contexte reçu, pour vérifier le câblage."""

    def __init__(self) -> None:
        self.last_context: str | None = None

    def invoke(self, system: str, context: str, message: str) -> str:
        self.last_context = context
        return "reponse test"


def test_fallback_receives_rendered_memory_context(db_session, kb):
    llm = RecordingLLM()
    memory = MemoryManager()
    agent = Agent(llm=llm, memory=memory, guardrails=GuardrailEngine(), session=db_session, kb=kb)

    memory.remember_fact("unit-wiring", "pointure", "L")
    agent.respond("unit-wiring", "Message hors gabarit connu, sans mot-cle metier.")

    assert llm.last_context is not None
    assert "pointure: L" in llm.last_context
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_memory_wiring.py -v`
Expected: FAIL — `assert llm.last_context is not None` fails (`last_context` stays `""`/unset because the current code passes a hardcoded empty string).

- [ ] **Step 3: Fix `src/velmo/agent.py`**

In `src/velmo/agent.py`, replace:

```python
    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            refusal = gate_in.refusal or DEFAULT_REFUSAL
            self.memory.write(user_id, message, refusal)
            return refusal

        self.memory.read(user_id, message)
        answer = self._handle(user_id, message)
```

with:

```python
    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            refusal = gate_in.refusal or DEFAULT_REFUSAL
            self.memory.write(user_id, message, refusal)
            return refusal

        context = self.memory.read(user_id, message)
        answer = self._handle(user_id, message, context)
```

Then replace:

```python
    def _handle(self, user_id: str, message: str) -> str:
```

with:

```python
    def _handle(self, user_id: str, message: str, context: MemoryContext) -> str:
```

Then replace the final fallback line:

```python
        return self.llm.invoke(SYSTEM_PROMPT, "", message)
```

with:

```python
        return self.llm.invoke(SYSTEM_PROMPT, context.render(), message)
```

Finally, add the import at the top of `src/velmo/agent.py` (alongside the existing `from .memory import MemoryManager` line):

```python
from .memory import MemoryContext, MemoryManager
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_agent_memory_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent.py tests/unit/test_agent_memory_wiring.py
git commit -m "fix(agent): wire rendered memory context into the LLM fallback call"
```

---

### Task 7: Full suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`

Expected: all tests in `tests/unit/` and `tests/acceptance/test_memory.py` PASS. `tests/acceptance/test_guardrails.py` and `tests/acceptance/test_mlops.py` are expected to still FAIL (out of scope — separate chantiers 003/006/007). `tests/acceptance/test_business.py` must still PASS unchanged (no regression).

- [ ] **Step 2: Run lint and type checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: no errors. Fix any `mypy`/`ruff` complaints in the new modules before proceeding (e.g. missing return type annotations).

- [ ] **Step 3: Update `ROADMAP.md`**

In `ROADMAP.md`, change the row:

```
| **001** | Mémoire court terme | Fil de conversation, fenêtre glissante, overflow → long terme | ✅ | ⬜ *(à regénérer)* | ⬜ | ⬜ *(stub `MemoryManager`)* |
```

to:

```
| **001** | Mémoire court terme | Fil de conversation, fenêtre glissante, overflow → long terme | ✅ | ✅ *(voir docs/superpowers/plans/2026-07-07-memory-manager-langgraph.md)* | ✅ | ✅ |
```

and the row:

```
| **002** | Mémoire long terme & RGPD | Faits durables sémantiques + épisodiques (ChromaDB), droit à l'oubli, traçabilité | ✅ | ⬜ *(à regénérer)* | ⬜ | ⬜ |
```

to:

```
| **002** | Mémoire long terme & RGPD | Faits durables sémantiques + épisodiques (ChromaDB), droit à l'oubli, traçabilité | ✅ | ✅ *(voir docs/superpowers/plans/2026-07-07-memory-manager-langgraph.md)* | ✅ | ✅ |
```

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: mark 001/002 memory chantiers as implemented"
```

---

## Out of scope (separate, later plan)

Replacing the free-form LLM fallback in `Agent._handle()` with a LangGraph `create_react_agent` tool-calling loop is **not** part of this plan — it is independently testable and will be planned separately, per `docs/superpowers/specs/2026-07-06-agent-runtime-langgraph-design.md`. This plan only touches memory (`MemoryManager`) and the one-line context-wiring bug fix in `agent.py`.
