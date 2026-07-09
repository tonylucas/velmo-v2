# Mémoire court terme (chantier 002) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à l'agent une mémoire de conversation court terme via le checkpointer LangGraph, en supprimant le gestionnaire de mémoire maison `MemoryManager`.

**Architecture:** Le graphe est compilé avec un checkpointer (`InMemorySaver` hors-ligne / `PostgresSaver` en prod), keyé par `thread_id = user_id`. `Agent.respond` n'invoque le graphe qu'avec le nouveau message ; le runtime charge et persiste l'historique. Une **soft window** borne le prompt LLM aux 30 derniers messages sans jamais élaguer le state persisté. R4 « sans perte » (Chroma épisodique) et le long terme (R2/R3-faits/R5/R6) partent au chantier 003.

**Tech Stack:** Python 3.11, uv, LangGraph (`InMemorySaver`, `StateGraph`, `add_messages`), LangChain (`create_agent`), pytest.

## Global Constraints

- **Gestion de paquets : `uv`.** Toute commande passe par `uv run ...`. Aucune modification de `pyproject.toml` n'est nécessaire (les paquets `langgraph`/`langchain` sont déjà en dépendances cœur).
- **Pas de `mypy`.** La vérification se fait **uniquement** par `pytest`. Ne pas lancer `make typecheck` (il reformaterait tout le repo). `make lint`/`make fmt` (ruff) restent autorisés et souhaitables.
- **Code en anglais** (identifiants, noms de fichiers, messages de commit, docstrings, commentaires). Seuls les textes destinés à l'utilisateur final de Velmo restent en français.
- **`pydantic`** pour toute structure de données typée nouvelle (aucune n'est requise ici : les états sont des `TypedDict` LangGraph et les messages des `BaseMessage`).
- **Découpage propre** : un fichier = une responsabilité. `get_checkpointer` dans son module ; la logique de fenêtre et de lecture d'état dans `agent_graph`.
- **Périmètre 002 = court terme strict.** On casse volontairement le long terme (R2/R3-faits/R5/R6) : leurs tests d'acceptance sont mis en `skip` avec renvoi au chantier 003. Ne pas tenter de les faire passer.
- **`thread_id = user_id`.** Isolation court terme R3 garantie par construction.
- **Soft window = 30 messages.** Le checkpointer conserve l'historique complet ; seule la liste passée au LLM est tronquée aux 30 derniers messages.
- **Vérif d'état = `graph.get_state`** (API haut niveau), jamais de manipulation bas niveau du checkpointer.

**Référence de conception :** `docs/superpowers/specs/2026-07-08-memory-short-term-design.md`.

---

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/velmo/memory/checkpointer.py` | Factory `get_checkpointer()` : backend mémoire court terme (InMemory / Postgres) | **Créer** |
| `src/velmo/agent_graph.py` | Graphe : branchement du checkpointer, soft window sur l'entrée LLM, lecture d'état `get_state` | **Modifier** |
| `src/velmo/agent.py` | `Agent` sans `MemoryManager` : détient un checkpointer, `respond` passe `thread_id`, expose `get_state` | **Modifier** |
| `src/velmo/memory/__init__.py` | Vidé de `MemoryManager`/`MemoryContext` : devient le docstring du pilier mémoire (le package reste, foyer du long terme en 003) | **Modifier** |
| `tests/test_checkpointer.py` | Tests de la factory | **Créer** |
| `tests/test_agent_graph.py` | Tests persistance / isolation / soft window (ajouts) | **Modifier** |
| `tests/test_agent.py` | Tests niveau `Agent` : rétention, isolation, `get_state` | **Créer** |
| `tests/acceptance/test_memory.py` | Recall R1 réécrit (vert) ; R2/R3-faits/R5 en `skip` (003) | **Modifier** |
| `CLAUDE.md` | Section mémoire mise à jour (checkpointer, plus de `MemoryManager`) | **Modifier** |

---

## Task 1: Checkpointer factory

**Files:**
- Create: `src/velmo/memory/checkpointer.py`
- Test: `tests/test_checkpointer.py`

**Interfaces:**
- Consumes: rien.
- Produces: `get_checkpointer() -> BaseCheckpointSaver`. Hors-ligne (pas de `DB_URL`) → une **nouvelle** instance `InMemorySaver` à chaque appel (isolation par agent).

- [ ] **Step 1: Write the failing test**

Create `tests/test_checkpointer.py`:

```python
"""Tests for the short-term memory checkpointer factory."""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from velmo.memory.checkpointer import get_checkpointer


def test_offline_returns_in_memory_saver(monkeypatch):
    monkeypatch.delenv("DB_URL", raising=False)
    assert isinstance(get_checkpointer(), InMemorySaver)


def test_each_call_returns_a_fresh_saver(monkeypatch):
    # A fresh saver per call keeps per-agent conversations isolated in tests.
    monkeypatch.delenv("DB_URL", raising=False)
    assert get_checkpointer() is not get_checkpointer()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_checkpointer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'velmo.memory.checkpointer'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/velmo/memory/checkpointer.py`:

```python
"""Checkpointer factory: the LangGraph short-term memory backend.

`InMemorySaver` offline (tests, eval); `PostgresSaver` when `DB_URL` is set and
the Postgres checkpointer package is installed. Symmetrical to `get_kb()` /
`get_chat_model()`.

The Postgres branch is the prod seam: it is not exercised by the offline suite
(no `DB_URL`) and is finalised when a real Postgres is connected.
"""

from __future__ import annotations

import os

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def get_checkpointer() -> BaseCheckpointSaver:
    """Return the Postgres checkpointer if configured, else the in-memory one."""
    db_url = os.getenv("DB_URL")
    if not db_url:
        return InMemorySaver()
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        return InMemorySaver()
    from psycopg import Connection

    conninfo = db_url.replace("postgresql+psycopg://", "postgresql://")
    conn = Connection.connect(conninfo, autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_checkpointer.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/checkpointer.py tests/test_checkpointer.py
git commit -m "feat: add get_checkpointer factory (InMemorySaver offline)"
```

---

## Task 2: Persist conversation history via the checkpointer

**Files:**
- Modify: `src/velmo/agent_graph.py`
- Test: `tests/test_agent_graph.py`

**Interfaces:**
- Consumes: `AgentState`, `build_graph`, `answer` (chantier 001) ; `InMemorySaver`.
- Produces:
  - `build_graph(session, user_id, kb, chat_model, context="", checkpointer=None)` — compile avec le checkpointer (ou sans si `None`, comportement chantier 001).
  - `answer(session, user_id, kb, message, context="", chat_model=None, checkpointer=None, thread_id=None) -> str` — si `checkpointer` fourni, invoque avec `config={"configurable": {"thread_id": thread_id}}` et seulement le nouveau message.
  - `get_state(checkpointer, thread_id) -> list[BaseMessage]` — messages persistés du thread (`[]` si aucun).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_graph.py` (add imports at top if missing: `from conftest import ScriptedToolCallingChatModel, seeded_session`, `from langchain_core.messages import AIMessage`, `from langgraph.checkpoint.memory import InMemorySaver`, and `from velmo.agent_graph import answer, build_graph, get_state`):

```python
def test_checkpointer_persists_history_across_turns():
    session = seeded_session()
    ck = InMemorySaver()
    model = ScriptedToolCallingChatModel(
        responses=[AIMessage(content="ok1"), AIMessage(content="ok2")]
    )
    answer(
        session, "C-marc-dubois", None, "Bonjour Velmo",
        chat_model=model, checkpointer=ck, thread_id="C-marc-dubois",
    )
    answer(
        session, "C-marc-dubois", None, "Une question de plus",
        chat_model=model, checkpointer=ck, thread_id="C-marc-dubois",
    )
    contents = [m.content for m in get_state(ck, "C-marc-dubois")]
    assert "Bonjour Velmo" in contents
    assert "Une question de plus" in contents


def test_threads_are_isolated_by_user():
    session = seeded_session()
    ck = InMemorySaver()
    model = ScriptedToolCallingChatModel(
        responses=[AIMessage(content="a"), AIMessage(content="b")]
    )
    answer(
        session, "C-marc-dubois", None, "mot secret artichaut",
        chat_model=model, checkpointer=ck, thread_id="C-marc-dubois",
    )
    answer(
        session, "C-sophie-martin", None, "coucou",
        chat_model=model, checkpointer=ck, thread_id="C-sophie-martin",
    )
    sophie = [m.content for m in get_state(ck, "C-sophie-martin")]
    assert not any("artichaut" in c for c in sophie)


def test_get_state_empty_thread_returns_empty():
    assert get_state(InMemorySaver(), "nobody") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_graph.py -k "checkpointer or isolated or empty_thread" -v`
Expected: FAIL with `ImportError: cannot import name 'get_state'` (and the new params not yet accepted).

- [ ] **Step 3: Write minimal implementation**

Edit `src/velmo/agent_graph.py`. Change the `build_graph` signature and its `compile` call, add the window-free `llm_node` unchanged for now, and add `answer` params + `get_state`. Full new file body:

```python
"""Assembles the Velmo agent as a single LangGraph StateGraph.

Two nodes:
- deterministic_node: the regex fast path (velmo.routing). No LLM call.
- llm_node: a ReAct agent (langchain create_agent) with the business tools,
  reached only when the deterministic path matches nothing.

Short-term memory is the checkpointer: compiled into the graph and keyed by
thread_id, it holds the conversation history across turns. `answer` invokes the
graph with only the new message; the runtime loads and persists the rest.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .agent_tools import build_tools
from .llm import get_chat_model
from .routing import SYSTEM_PROMPT, run_deterministic


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    matched: bool


def build_graph(
    session,
    user_id: str,
    kb,
    chat_model: BaseChatModel,
    context: str = "",
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the two-node agent graph bound to one request."""

    def deterministic_node(state: AgentState) -> dict:
        message = state["messages"][-1].content
        reply = run_deterministic(session, user_id, kb, message)
        if reply is None:
            return {"matched": False}
        return {"messages": [AIMessage(content=reply)], "matched": True}

    def route(state: AgentState) -> Literal["llm_node", "__end__"]:
        return END if state.get("matched") else "llm_node"

    system_prompt = SYSTEM_PROMPT
    if context:
        system_prompt = f"{SYSTEM_PROMPT}\n\nMémoire:\n{context}"
    react = create_agent(
        model=chat_model,
        tools=build_tools(session, user_id, kb),
        system_prompt=system_prompt,
    )

    def llm_node(state: AgentState) -> dict:
        result = react.invoke({"messages": state["messages"]})
        return {"messages": result["messages"]}

    graph = StateGraph(AgentState)
    graph.add_node("deterministic_node", deterministic_node)
    graph.add_node("llm_node", llm_node)
    graph.set_entry_point("deterministic_node")
    graph.add_conditional_edges(
        "deterministic_node", route, {"llm_node": "llm_node", END: END}
    )
    graph.add_edge("llm_node", END)
    return graph.compile(checkpointer=checkpointer)


def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    graph = build_graph(session, user_id, kb, chat_model, context, checkpointer)
    config = (
        {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)], "matched": False},
        config,
    )
    return result["messages"][-1].content


def _state_reader_graph(checkpointer: BaseCheckpointSaver):
    """A minimal graph sharing AgentState's channels, used to read persisted state."""
    graph = StateGraph(AgentState)
    graph.add_node("noop", lambda state: {})
    graph.set_entry_point("noop")
    graph.add_edge("noop", END)
    return graph.compile(checkpointer=checkpointer)


def get_state(checkpointer: BaseCheckpointSaver, thread_id: str) -> list[BaseMessage]:
    """Return the conversation messages persisted for a thread (empty if none)."""
    graph = _state_reader_graph(checkpointer)
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    return snapshot.values.get("messages", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_graph.py -v`
Expected: PASS — the three chantier-001 tests still pass (checkpointer defaults to `None`), plus the three new ones.

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent_graph.py tests/test_agent_graph.py
git commit -m "feat: persist conversation history via the graph checkpointer"
```

---

## Task 3: Sliding window on the LLM input

**Files:**
- Modify: `src/velmo/agent_graph.py`
- Test: `tests/test_agent_graph.py`

**Interfaces:**
- Consumes: `answer`, `get_state`, `AgentState` (Task 2).
- Produces:
  - `WINDOW_SIZE = 30`
  - `window_messages(messages: list[BaseMessage], limit: int = WINDOW_SIZE) -> list[BaseMessage]` — les `limit` derniers messages.
  - `llm_node` passe désormais `window_messages(state["messages"])` à l'agent ReAct (le state persisté n'est pas tronqué).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_graph.py` (add imports: `from langchain_core.messages import HumanMessage, SystemMessage`, `from velmo.agent_graph import window_messages`):

```python
def test_window_messages_keeps_last_n():
    msgs = [HumanMessage(content=str(i)) for i in range(50)]
    windowed = window_messages(msgs, 30)
    assert len(windowed) == 30
    assert windowed[0].content == "20"
    assert windowed[-1].content == "49"


def test_window_messages_shorter_than_limit_unchanged():
    msgs = [HumanMessage(content=str(i)) for i in range(5)]
    assert window_messages(msgs, 30) == msgs


def test_llm_input_is_windowed_but_state_keeps_all():
    session = seeded_session()
    ck = InMemorySaver()
    seen: list[int] = []

    class Recorder(ScriptedToolCallingChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(sum(1 for m in messages if not isinstance(m, SystemMessage)))
            return super()._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )

    model = Recorder(responses=[AIMessage(content="ok")])
    user = "C-marc-dubois"
    for i in range(40):
        answer(
            session, user, None, f"Message numero {i} sans intention.",
            chat_model=model, checkpointer=ck, thread_id=user,
        )
    # The LLM never receives more than the window; the checkpointer keeps everything.
    assert max(seen) <= 30
    assert len(get_state(ck, user)) > 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_graph.py -k "window" -v`
Expected: FAIL with `ImportError: cannot import name 'window_messages'`.

- [ ] **Step 3: Write minimal implementation**

Edit `src/velmo/agent_graph.py`. Add the constant and helper just after the imports (below `AgentState`), and change `llm_node`.

Add after the `AgentState` class:

```python
WINDOW_SIZE = 30


def window_messages(
    messages: list[BaseMessage], limit: int = WINDOW_SIZE
) -> list[BaseMessage]:
    """Return at most the last `limit` messages — the sliding window fed to the LLM.

    The persisted state is never trimmed (soft window): the checkpointer keeps
    the full history; only the model's working context is bounded here.
    """
    return messages[-limit:]
```

Change `llm_node` inside `build_graph` from:

```python
    def llm_node(state: AgentState) -> dict:
        result = react.invoke({"messages": state["messages"]})
        return {"messages": result["messages"]}
```

to:

```python
    def llm_node(state: AgentState) -> dict:
        windowed = window_messages(state["messages"])
        result = react.invoke({"messages": windowed})
        return {"messages": result["messages"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_graph.py -v`
Expected: PASS (all agent-graph tests, including the three window tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent_graph.py tests/test_agent_graph.py
git commit -m "feat: bound the LLM prompt with a 30-message sliding window"
```

---

## Task 4: Cut Agent over to the checkpointer, drop MemoryManager wiring

**Files:**
- Modify: `src/velmo/agent.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `agent_graph.answer`, `agent_graph.get_state` (Tasks 2-3) ; `get_checkpointer` (Task 1).
- Produces:
  - `Agent(chat_model, guardrails, session=None, kb=None, checkpointer=None)` — plus de paramètre `memory` ; détient un checkpointer (défaut `get_checkpointer()`).
  - `Agent.respond(user_id, message) -> str` — passe `thread_id=user_id` et le checkpointer au graphe.
  - `Agent.get_state(user_id) -> list[BaseMessage]` — délègue à `agent_graph.get_state`.
  - `build_default_agent(session=None, kb=None) -> Agent` — sans `MemoryManager`.
  - conftest : `build_reference_agent()` / `build_degraded_agent()` sans `MemoryManager`.

> Note : ce task ne touche pas `src/velmo/memory/` ni `tests/acceptance/test_memory.py`. Le module `memory` reste présent (ses 4 tests d'acceptance restent rouges comme dans le baseline). Le nettoyage final est le Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent.py`:

```python
"""Tests for the Agent short-term memory (checkpointer-backed)."""

from __future__ import annotations

from conftest import build_reference_agent


def test_agent_retains_conversation_across_turns():
    agent = build_reference_agent()
    user = "C-marc-dubois"
    agent.respond(user, "Retiens ce mot: artichaut.")
    agent.respond(user, "Autre message sans rapport.")
    contents = [m.content for m in agent.get_state(user)]
    assert any("artichaut" in c for c in contents)


def test_agent_isolates_users():
    agent = build_reference_agent()
    agent.respond("C-marc-dubois", "mot secret artichaut")
    agent.respond("C-sophie-martin", "bonjour")
    sophie = [m.content for m in agent.get_state("C-sophie-martin")]
    assert not any("artichaut" in c for c in sophie)


def test_agent_unknown_user_has_empty_state():
    agent = build_reference_agent()
    assert agent.get_state("C-karim-benali") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent.py -v`
Expected: FAIL with `TypeError` (Agent still requires `memory=`) or `AttributeError: 'Agent' object has no attribute 'get_state'`.

- [ ] **Step 3: Write minimal implementation**

Replace the whole `src/velmo/agent.py` with:

```python
"""Agent Velmo 2.0 : garde-fou d'entrée → graphe (routage déterministe + nœud LLM
outillé, mémoire court terme via checkpointer) → garde-fou de sortie → réponse.

Le fil de conversation est persisté par le checkpointer LangGraph
(`thread_id = user_id`) ; il n'y a plus de gestionnaire de mémoire maison. Les
garde-fous de contenu sont encore des stubs (chantier 004).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from . import agent_graph
from .guardrails import GuardrailEngine
from .memory.checkpointer import get_checkpointer

DEFAULT_REFUSAL = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)


class Agent:
    """Assistant de support adossé au graphe (routage déterministe + LLM outillé)."""

    def __init__(
        self,
        chat_model: BaseChatModel | None,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.guardrails = guardrails
        self.session = session
        self.kb = kb
        self.checkpointer: BaseCheckpointSaver = checkpointer or get_checkpointer()

    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            return gate_in.refusal or DEFAULT_REFUSAL

        answer = agent_graph.answer(
            self.session,
            user_id,
            self.kb,
            message,
            chat_model=self.chat_model,
            checkpointer=self.checkpointer,
            thread_id=user_id,
        )

        gate_out = self.guardrails.check_output(answer)
        if not gate_out.allowed:
            answer = gate_out.refusal or DEFAULT_REFUSAL
        return answer

    def get_state(self, user_id: str):
        """Return the conversation messages retained for a user (traceability)."""
        return agent_graph.get_state(self.checkpointer, user_id)


def build_default_agent(session=None, kb=None) -> Agent:
    """Assemble un agent avec composants par défaut, base et FAQ."""
    from .db import session_factory
    from .kb_store import get_kb
    from .llm import get_chat_model

    if session is None:
        session = session_factory()()
    if kb is None:
        kb = get_kb()
    return Agent(
        chat_model=get_chat_model(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=kb,
    )
```

Edit `tests/conftest.py`:

1. Remove the import line `from velmo.memory import MemoryManager`.
2. Replace `build_reference_agent` and `build_degraded_agent` with:

```python
def build_reference_agent() -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=GuardrailEngine(),
        session=seeded_session(),
        kb=LocalKB(),
    )


def build_degraded_agent() -> Agent:
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=AllowAllGuardrails(),
        session=seeded_session(),
        kb=LocalKB(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent.py tests/acceptance/test_business.py -v`
Expected: PASS for `tests/test_agent.py` (3) and the business acceptance tests (they build agents via the fixtures).

Then run the whole suite to confirm no unexpected breakage:
Run: `uv run pytest tests/ -q`
Expected: the only failures are the pre-existing red stubs — `tests/acceptance/test_guardrails.py` (5), `tests/acceptance/test_memory.py` (4, still on the old `MemoryManager`), `tests/acceptance/test_mlops.py` (3). No other failures.

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent.py tests/conftest.py tests/test_agent.py
git commit -m "feat: back Agent short-term memory with the checkpointer, drop memory param"
```

---

## Task 5: Rewrite memory acceptance tests, delete MemoryManager, update docs

**Files:**
- Modify: `tests/acceptance/test_memory.py`
- Modify: `src/velmo/memory/__init__.py` (retire `MemoryManager`/`MemoryContext`, garde le package)
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `build_reference_agent` (conftest), `Agent.respond`, `Agent.get_state` (Task 4).
- Produces: acceptance suite alignée sur le périmètre 002 ; le package `memory/` reste le foyer du pilier mémoire (`checkpointer.py` présent, long terme à venir en 003).

- [ ] **Step 1: Rewrite the acceptance test file**

Replace the whole `tests/acceptance/test_memory.py` with:

```python
"""Tests d'acceptance — mémoire court terme (chantier 002).

R1 (fil de conversation) est couvert via l'agent + le checkpointer : on assère
sur l'état retenu (`Agent.get_state`), déterministe hors-ligne. R2 / R3 (faits) /
R5 relèvent du Store long terme et sont repris au chantier 003 (skip ci-dessous).
"""

from __future__ import annotations

import pytest

from conftest import build_reference_agent


def test_recall_over_30_messages():
    # R1 : l'info du 1er message est restituée après 30+ messages. Soft window :
    # le checkpointer conserve l'historique complet du thread.
    agent = build_reference_agent()
    user = "acc-recall"
    agent.respond(user, "Ma commande prioritaire est O-2024-0101.")
    for i in range(30):
        agent.respond(user, f"Question de suivi {i} sur un maillot.")

    contents = [m.content for m in agent.get_state(user)]
    assert any("O-2024-0101" in c for c in contents)


@pytest.mark.skip(reason="R2 — mémoire long terme cross-session : chantier 003 (Store)")
def test_cross_session_persistence():
    """Faits durables retrouvés une nouvelle session (Store, pas le checkpointer)."""


@pytest.mark.skip(reason="R3 faits — isolation du Store long terme : chantier 003")
def test_isolation_between_customers():
    """Les faits durables d'un client ne fuitent jamais chez un autre (Store)."""


@pytest.mark.skip(reason="R5 — droit à l'oubli sur le Store long terme : chantier 003")
def test_right_to_be_forgotten():
    """« Oublie mon adresse » supprime effectivement l'information (Store.delete)."""
```

- [ ] **Step 2: Run the acceptance test to verify recall passes and the rest skips**

Run: `uv run pytest tests/acceptance/test_memory.py -v`
Expected: `test_recall_over_30_messages` PASS ; the three others SKIPPED. 0 failed.

- [ ] **Step 3: Remove MemoryManager from the memory package (keep the package)**

Replace the whole `src/velmo/memory/__init__.py` with a package docstring only (the `MemoryManager` and `MemoryContext` classes are dropped; `checkpointer.py` stays in this package):

```python
"""Mémoire de l'agent Velmo — pilier mémoire du projet.

La mémoire **court terme** (fil de conversation, fenêtre glissante) est le
checkpointer LangGraph — voir `velmo.memory.checkpointer`. La mémoire **long
terme** (faits durables, épisodique Chroma, droit à l'oubli) sera ajoutée dans ce
package au chantier 003. Il n'y a plus de gestionnaire de mémoire maison.
"""
```

- [ ] **Step 4: Verify MemoryManager is gone and the suite is clean**

Run: `grep -rn "MemoryManager\|MemoryContext" src/ tests/`
Expected: no output (the bespoke store is fully removed). The `velmo.memory.checkpointer` import remains and is expected.

Run: `uv run pytest tests/ -q`
Expected: failures reduced to the remaining red stubs only — `tests/acceptance/test_guardrails.py` (5) and `tests/acceptance/test_mlops.py` (3). `tests/acceptance/test_memory.py` now passes (1 passed, 3 skipped). No import errors.

- [ ] **Step 5: Update CLAUDE.md**

Make three edits in `CLAUDE.md`:

**Edit A** — the pipeline diagram. Replace:

```
message → guardrails.check_input → memory.read → graphe LangGraph (routage déterministe → nœud LLM outillé) → guardrails.check_output → memory.write → réponse
```

with:

```
message → guardrails.check_input → graphe LangGraph (mémoire court terme via checkpointer ; routage déterministe → nœud LLM outillé) → guardrails.check_output → réponse
```

**Edit B** — add one sentence about short-term memory right after the paragraph ending `build_degraded_agent avec des SQLite seedées et OfflineChatModel/LocalKB).` Insert this paragraph:

```
La **mémoire court terme** est le checkpointer LangGraph (`velmo.memory.checkpointer.get_checkpointer` :
`InMemorySaver` hors-ligne, `PostgresSaver` si `DB_URL`), compilé dans le graphe et keyé par
`thread_id = user_id`. `Agent.respond` n'invoque qu'avec le nouveau message ; le runtime charge et
persiste l'historique. Une **soft window** (`agent_graph.window_messages`, 30 messages) borne le prompt
LLM sans élaguer le state (`Agent.get_state(user_id)` restitue l'historique complet). Il n'y a plus de
`MemoryManager` maison.
```

**Edit C** — replace the `memory/` bullet under « Trois modules à construire ». Replace:

```
- **`memory/`** (`MemoryManager`) : `read(user_id, message) -> MemoryContext`,
  `write(user_id, user_msg, assistant_msg)`, `remember_fact`, `forget`, `inspect`. Doit satisfaire R1-R6
  du brief (30 tours, persistance cross-session, isolation stricte par `user_id`, résumé au-delà de 30
  messages, droit à l'oubli vérifiable, traçabilité). La reco stack impose Chroma pour l'épisodique long
  terme ; le sémantique (faits durables) reste à concevoir (clé-valeur ? faits typés ?).
```

with:

```
- **Mémoire long terme (chantier 003, à construire)** : Store LangGraph (`BaseStore`) namespacé par
  `user_id` pour les faits durables (R2/R3), droit à l'oubli (R5) et inspection (R6), plus l'épisodique
  Chroma pour R4 « résumer/sélectionner sans perte ». La mémoire **court terme** (R1 + fenêtre glissante)
  est faite : c'est le checkpointer (voir le pipeline ci-dessus). L'ancien `MemoryManager` maison a été
  supprimé au chantier 002.
```

- [ ] **Step 6: Commit**

```bash
git add tests/acceptance/test_memory.py src/velmo/memory/__init__.py CLAUDE.md
git commit -m "feat: short-term memory acceptance via agent + checkpointer, remove MemoryManager"
```

---

## Self-Review

**1. Spec coverage** (against `2026-07-08-memory-short-term-design.md`):
- Checkpointer factory (§3.1) → Task 1. ✅
- Persistance R1 + `thread_id=user_id` + isolation court terme R3 (§3, §2.2) → Task 2. ✅
- Soft window 30 messages (§3.2) → Task 3. ✅
- Suppression `MemoryManager`, `Agent` sans `memory`, `build_default_agent`, conftest (§1, §6) → Tasks 4-5. ✅
- Recall réécrit sur `get_state` (§5.1) → Task 5. ✅
- Tests unitaires fenêtre + persistance (§5.2) → Tasks 2-3. ✅
- R2/R3-faits/R5 en skip (§5.3) → Task 5. ✅
- `get_state` amorce R6 (§8) → Tasks 2/4. ✅
- CLAUDE.md (§6) → Task 5. ✅
- Déféré 003 (§4) : Store, Chroma, R4 sans perte — hors plan, correct.

**2. Placeholder scan:** aucun « TBD/TODO » dans le code produit ; les `skip` sont des renvois de périmètre explicites, pas des placeholders de plan. Chaque step de code contient le code complet. ✅

**3. Type consistency:** `get_checkpointer() -> BaseCheckpointSaver` (Task 1) consommé par `Agent.checkpointer` (Task 4) et `answer(..., checkpointer=...)` (Task 2). `get_state(checkpointer, thread_id) -> list[BaseMessage]` (Task 2) appelé par `Agent.get_state` (Task 4) et les tests. `window_messages(messages, limit=WINDOW_SIZE)` (Task 3) utilisé dans `llm_node`. `answer(..., checkpointer=None, thread_id=None)` cohérent entre Task 2 (définition) et Task 4 (appel avec `thread_id=user_id`). ✅

**Points de vigilance connus (repris du design, non bloquants) :** wiring `PostgresSaver` prod non couvert hors-ligne (Task 1, branche gardée) ; croissance du state en soft window (élagage réel = chantier 003).
