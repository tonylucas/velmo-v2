# Agent LangGraph (chantier 001) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le fallback echo de `Agent._handle` par un vrai agent LangGraph (routage déterministe + nœud LLM outillé) réuni dans un seul `StateGraph`.

**Architecture:** Tout l'agent devient un `StateGraph` à deux nœuds. `deterministic_node` rejoue la logique regex existante (aucun LLM) et, s'il ne reconnaît rien, route vers `llm_node` — un agent ReAct `create_agent` avec les 10 outils métier fermés sur `session`/`user_id`/`kb`. `Agent.respond` reste l'enveloppe pipeline (garde-fous → mémoire → graphe → garde-fous → mémoire).

**Tech Stack:** Python 3.11, uv, LangChain 1.3 (`create_agent`), LangGraph 1.2 (`StateGraph`), pydantic 2, pytest. LLM réel via Azure AI Inference (Kimi-K2.6) ; repli hors-ligne `OfflineChatModel`.

## Global Constraints

- Gestionnaire de paquets : **uv** exclusivement (`uv run`, `uv sync`). Jamais `pip`/`poetry`.
- Code, identifiants, docstrings, commentaires, messages de commit : **en anglais**. Seuls les textes destinés au client Velmo (réponses, refus) restent en français.
- **Ne pas lancer mypy** (il reformaterait tout le repo et rendrait la PR illisible). Vérification = pytest uniquement.
- Découpage propre : un fichier = une responsabilité (routage / outils / graphe / pipeline séparés).
- pydantic pour la validation. Les schémas d'arguments des outils sont générés par le décorateur `@tool` de LangChain à partir des signatures typées et docstrings (pydantic sous le capot).
- **Isolation stricte par `user_id`** : le LLM ne doit jamais pouvoir choisir `user_id`. Les outils ferment dessus.
- Ne pas modifier `src/velmo/db.py` ni `src/velmo/tools/*.py`.
- Ne pas modifier le contenu de `tests/acceptance/` (ce sont les contrats). On peut ajouter de nouveaux fichiers de test hors `tests/acceptance/`.
- `memory/` et `guardrails/` restent des stubs no-op (hors périmètre de ce chantier).
- Graphe compilé **sans checkpointer** (`.compile()` sans argument) pour ce chantier.
- **Baseline de tests** : à l'état initial, `tests/acceptance/test_business.py` = 7 passés ; les suites memory/guardrails/mlops échouent (stubs d'autres chantiers) — c'est normal, on ne les touche pas. La cible de validation par tâche est `test_business.py` + les nouveaux fichiers de test, **jamais** la suite complète.
- **Écart assumé vs spec** : le spec disait « aucune nouvelle dépendance ». On relocalise `langchain` + `langchain-core` de l'extra `llm` vers les dépendances cœur (aucun paquet réellement nouveau dans `uv.lock` ; `langgraph` arrive transitivement). Raison : l'agent dépend désormais de LangGraph et la CI fait `uv sync` sans extras.

---

## File Structure

- `pyproject.toml` — déplace `langchain`/`langchain-core` vers les deps cœur (Task 1).
- `src/velmo/llm.py` — **remplacé** : `OfflineChatModel(BaseChatModel)` + `get_chat_model()`. Retire `EchoLLM`/`AzureLLM`/`LLM`/`get_llm` (Task 1 ajoute, Task 5 retire le mort).
- `src/velmo/routing.py` — **nouveau** : `run_deterministic(session, user_id, kb, message) -> str | None` + helpers de formatage. La logique regex de l'ancien `_handle`, en fonction pure (Task 2).
- `src/velmo/agent_tools.py` — **nouveau** : `build_tools(session, user_id, kb) -> list[BaseTool]`, les 10 outils LLM fermés sur le contexte (Task 3).
- `src/velmo/agent_graph.py` — **nouveau** : `AgentState`, `build_graph(...)`, `answer(...)` (Task 4).
- `src/velmo/agent.py` — **allégé** : `Agent` perd `_handle` et les helpers ; `respond` appelle `agent_graph.answer` ; `__init__` prend `chat_model` (Task 5).
- `tests/test_llm.py` — nouveau (Task 1).
- `tests/test_routing.py` — nouveau (Task 2).
- `tests/test_agent_tools.py` — nouveau (Task 3).
- `tests/test_agent_graph.py` — nouveau (Task 4).
- `tests/conftest.py` — ajoute `ScriptedToolCallingChatModel` (Task 4) ; migre les fixtures vers `chat_model=OfflineChatModel()` (Task 5).

---

## Task 1: OfflineChatModel + get_chat_model (et deps cœur)

**Files:**
- Modify: `pyproject.toml` (blocs `dependencies` et `[project.optional-dependencies].llm`)
- Modify: `src/velmo/llm.py` (ajout de `OfflineChatModel` + `get_chat_model`, sans retirer l'existant)
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: rien (première tâche).
- Produces:
  - `velmo.llm.OfflineChatModel` — `BaseChatModel`, `bind_tools(tools, **kw) -> OfflineChatModel` (retourne self), `_generate(...)` renvoie un `AIMessage` d'accusé de réception.
  - `velmo.llm.get_chat_model() -> BaseChatModel` — `AzureAIOpenAIApiChatModel` si `AZURE_AI_INFERENCE_ENDPOINT`, sinon `OfflineChatModel`.

- [ ] **Step 1: Déplacer langchain vers les deps cœur**

Dans `pyproject.toml`, remplacer le bloc `dependencies` par :

```toml
dependencies = [
    "pydantic>=2.7,<3",
    "python-dotenv>=1.0",
    "sqlalchemy>=2.0,<2.1",
    "psycopg[binary]>=3.1,<3.3",
    "alembic>=1.13,<2",
    "langchain>=1.2,<2.0",
    "langchain-core>=1.0,<2.0",
]
```

et réduire l'extra `llm` à l'Azure uniquement :

```toml
# LLM via Azure AI Inference (Kimi-K2.6).
llm = [
    "langchain-azure-ai>=1.0,<2.0",
    "azure-ai-inference>=1.0.0b9",
]
```

- [ ] **Step 2: Synchroniser et vérifier l'import cœur**

Run: `uv sync && uv run python -c "from langchain.agents import create_agent; from langgraph.graph import StateGraph; print('ok')"`
Expected: la dernière ligne affiche `ok` (langchain/langgraph disponibles sans extra).

- [ ] **Step 3: Écrire le test qui échoue**

Créer `tests/test_llm.py` :

```python
"""Tests for the chat model factory and the offline fallback."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.llm import OfflineChatModel, get_chat_model


def test_offline_model_echoes():
    model = OfflineChatModel()
    reply = model.invoke([HumanMessage(content="Bonjour")])
    assert reply.content.startswith("[velmo]")
    assert "Bonjour" in reply.content


def test_offline_model_bind_tools_returns_self():
    model = OfflineChatModel()
    assert model.bind_tools([]) is model


def test_get_chat_model_offline_without_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_AI_INFERENCE_ENDPOINT", raising=False)
    assert isinstance(get_chat_model(), OfflineChatModel)
```

- [ ] **Step 4: Lancer le test pour le voir échouer**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL avec `ImportError: cannot import name 'OfflineChatModel'`.

- [ ] **Step 5: Ajouter `OfflineChatModel` et `get_chat_model` à `llm.py`**

Ajouter en tête de `src/velmo/llm.py` (après le docstring et `import os`) les imports :

```python
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
```

Puis ajouter, à la fin du fichier (sans rien supprimer pour l'instant) :

```python
class OfflineChatModel(BaseChatModel):
    """Deterministic offline chat model (no tool calling).

    Returns a plain acknowledgement so `make chat` and the LLM fallback path
    work without Azure credentials.
    """

    @property
    def _llm_type(self) -> str:
        return "velmo-offline"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "OfflineChatModel":
        # No tool calling offline; the model simply acknowledges the message.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        text = last_human.content if last_human else ""
        message = AIMessage(content=f"[velmo] J'ai bien reçu : {text}")
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_chat_model() -> BaseChatModel:
    """Return the Azure chat model if configured, else the offline fallback."""
    if not os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        return OfflineChatModel()

    from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel

    return AzureAIOpenAIApiChatModel(
        endpoint=os.environ["AZURE_AI_INFERENCE_ENDPOINT"],
        credential=os.environ["AZURE_AI_INFERENCE_API_KEY"],
        model=os.environ.get("AZURE_AI_INFERENCE_MODEL", "Kimi-K2.6"),
    )
```

- [ ] **Step 6: Lancer le test pour le voir passer**

Run: `uv run pytest tests/test_llm.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Vérifier la non-régression métier**

Run: `uv run pytest tests/acceptance/test_business.py -q`
Expected: `7 passed`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/velmo/llm.py tests/test_llm.py
git commit -m "feat: add OfflineChatModel and get_chat_model, move langchain to core deps"
```

---

## Task 2: routing.py — run_deterministic (fast path pur)

**Files:**
- Create: `src/velmo/routing.py`
- Test: `tests/test_routing.py`

**Interfaces:**
- Consumes: `velmo.tools` (fonctions métier existantes).
- Produces:
  - `velmo.routing.run_deterministic(session, user_id: str, kb, message: str) -> str | None` — renvoie la réponse formatée si une intention regex est reconnue, sinon `None`.
  - `velmo.routing.SYSTEM_PROMPT: str` — prompt système partagé (consommé par `agent_graph` en Task 4).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_routing.py` :

```python
"""Tests for the deterministic (regex) routing fast path."""

from __future__ import annotations

from conftest import seeded_session

from velmo.routing import run_deterministic


def test_order_status_is_recognised():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Quel est le statut de ma commande O-2024-0101 ?"
    )
    assert reply is not None
    assert "prepared" in reply


def test_out_of_stock_is_not_fabulated():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Le maillot om-1993 en taille M est-il disponible ?"
    )
    assert reply is not None
    assert "indisponible" in reply.lower()


def test_unknown_intent_returns_none():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Bonjour, pouvez-vous m'aider aujourd'hui ?"
    )
    assert reply is None


def test_isolation_other_customer_order():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Statut de la commande O-2024-0107 ?"
    )
    assert reply is not None
    assert "Je ne trouve pas" in reply
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `uv run pytest tests/test_routing.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'velmo.routing'`.

- [ ] **Step 3: Créer `src/velmo/routing.py`**

```python
"""Deterministic intent routing for the Velmo agent (the fast path).

Regex-based recognition of order operations, stock availability and FAQ
lookups. Calls the business tools directly, with no LLM involved. Returns None
when nothing matches, so the caller can fall back to the LLM agent.

This is the logic formerly held in `Agent._handle`, extracted verbatim into a
pure function so it can be unit-tested and wired as a graph node.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import tools

SYSTEM_PROMPT = (
    "Tu es l'assistant de support de Velmo, boutique de maillots de foot collector. "
    "Tu traites la gestion de commandes de niveau 1 avec courtoisie et précision."
)

ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
SIZE_RE = re.compile(r"\b(XXL|XL|S|M|L)\b")
AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|euros?)")
_CONFIRM = ("je confirme", "confirme", "c'est confirmé", "oui je", "vas-y")

# Alias conviviaux -> référence produit.
_ALIASES = {
    "om 1993": "om-1993",
    "marseille 1993": "om-1993",
    "france 98": "france-1998",
    "france 1998": "france-1998",
    "united 99": "mu-1999-treble",
    "mu 1999": "mu-1999-treble",
    "manchester 1999": "mu-1999-treble",
    "bresil 1970": "brazil-1970",
    "brésil 1970": "brazil-1970",
}

_FAQ_KEYWORDS = (
    "frais de port", "frais de livraison", "délai", "delai", "politique de retour",
    "authenticit", "certificat", "paiement", "réassort", "reassort", "rétractation",
    "retractation", "entretien", "garantie", "remboursement sous", "conditions d'échange",
)


def run_deterministic(session, user_id: str, kb, message: str) -> str | None:
    """Route a message to a business tool by regex. Return the reply, or None
    when no deterministic intent matches (LLM fallback)."""
    low = message.lower()
    order = ORDER_RE.search(message)
    order_id = order.group(0) if order else None
    confirmed = any(c in low for c in _CONFIRM)

    if order_id and "annul" in low:
        return _confirm_or_act(
            confirmed, "annuler", order_id,
            lambda: tools.cancel_order(session, order_id, user_id),
        )
    if order_id and "adresse" in low:
        return _confirm_or_act(
            confirmed, "modifier l'adresse de", order_id,
            lambda: tools.update_shipping_address(
                session, order_id, user_id, {"line1": "(à préciser)"}
            ),
        )
    if order_id and "taille" in low and any(w in low for w in ("chang", "modif", "tromp", "erreur")):
        size = SIZE_RE.search(message)
        new_size = size.group(1) if size else "M"
        return _confirm_or_act(
            confirmed, f"changer la taille (vers {new_size}) de", order_id,
            lambda: tools.update_order_item(session, order_id, user_id, new_size),
        )
    if order_id and any(w in low for w in ("retour", "échange", "echange", "renvoyer")):
        return _confirm_or_act(
            confirmed, "ouvrir un retour pour", order_id,
            lambda: tools.create_return(session, order_id, user_id, "Demande client"),
        )
    if order_id and "rembours" in low:
        amount_match = AMOUNT_RE.search(message)
        amount = float(amount_match.group(1).replace(",", ".")) if amount_match else 0.0
        return _confirm_or_act(
            confirmed, f"rembourser {amount:.0f}€ sur", order_id,
            lambda: tools.trigger_refund(session, order_id, user_id, amount, "Demande client"),
        )

    if order_id and any(w in low for w in ("suivi", "colis", "livr", "transport", "track")):
        return _format_tracking(tools.track_shipment(session, order_id, user_id))
    if order_id:
        return _format_order(tools.get_order(session, order_id, user_id))

    if any(w in low for w in ("dispo", "stock", "reste", "en taille")):
        return _handle_stock(session, message, low)

    if any(k in low for k in _FAQ_KEYWORDS):
        return _format_kb(tools.search_kb(kb, message))

    return None


def _confirm_or_act(confirmed: bool, label: str, order_id: str, action: Callable[[], dict]) -> str:
    if not confirmed:
        return (
            f"Pour {label} la commande {order_id}, pouvez-vous confirmer ? "
            "Répondez « je confirme »."
        )
    result = action()
    if result.get("error"):
        return f"Je ne trouve pas la commande {order_id} à votre nom."
    if result.get("action") == "escalate":
        return (
            f"Cette demande sur la commande {order_id} dépasse ce que je peux faire seul "
            "(commande déjà partie ou montant trop élevé). Je transmets à un conseiller."
        )
    return f"C'est fait pour la commande {order_id} ({result.get('action')})."


def _handle_stock(session, message: str, low: str) -> str:
    ref = _find_ref(session, low)
    size = SIZE_RE.search(message)
    if not ref or not size:
        return "Pouvez-vous préciser la référence du maillot et la taille souhaitée ?"
    result = tools.check_stock(session, ref, size.group(1))
    if result.get("error"):
        return "Je ne connais pas cette référence dans notre catalogue."
    if result["available"]:
        return f"Le maillot {result['title']} en taille {result['size']} est disponible."
    return f"Le maillot {ref} en taille {result['size']} est indisponible (épuisé)."


def _find_ref(session, low: str) -> str | None:
    for alias, ref in _ALIASES.items():
        if alias in low:
            return ref
    if session is not None:
        from .db import Product
        from .tools._common import select

        for (ref,) in session.execute(select(Product.ref)).all():
            if ref.lower() in low:
                return ref
    return None


def _format_order(result: dict) -> str:
    if result.get("error"):
        return "Je ne trouve pas cette commande à votre nom."
    return f"Votre commande {result['order_id']} est au statut « {result['status']} »."


def _format_tracking(result: dict) -> str:
    if result.get("error"):
        return "Je ne trouve pas cette commande à votre nom."
    if not result.get("tracking_number"):
        return f"La commande {result['order_id']} n'est pas encore expédiée."
    return (
        f"Votre colis {result['tracking_number']} ({result['carrier']}) est attendu vers "
        f"{result['estimated_delivery']}."
    )


def _format_kb(result: dict) -> str:
    if not result.get("found"):
        return "Je n'ai pas trouvé cette information dans notre FAQ."
    top = result["results"][0]
    return f"D'après notre FAQ ({top['source']}) : {top['snippet']}"
```

- [ ] **Step 4: Lancer le test pour le voir passer**

Run: `uv run pytest tests/test_routing.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/routing.py tests/test_routing.py
git commit -m "feat: extract deterministic routing into pure run_deterministic"
```

---

## Task 3: agent_tools.py — build_tools (outils LLM isolés)

**Files:**
- Create: `src/velmo/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `velmo.tools` (fonctions métier existantes).
- Produces:
  - `velmo.agent_tools.build_tools(session, user_id: str, kb) -> list[BaseTool]` — 10 outils LangChain fermés sur `session`/`user_id`/`kb`. Noms exacts : `get_order`, `track_shipment`, `check_stock`, `search_kb`, `update_order_item`, `update_shipping_address`, `cancel_order`, `create_return`, `trigger_refund`, `escalate_to_human`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_agent_tools.py` :

```python
"""Tests for the per-request LLM toolset (closure binding + isolation)."""

from __future__ import annotations

from conftest import seeded_session

from velmo.agent_tools import build_tools

_EXPECTED = {
    "get_order", "track_shipment", "check_stock", "search_kb",
    "update_order_item", "update_shipping_address", "cancel_order",
    "create_return", "trigger_refund", "escalate_to_human",
}


def _by_name(session, user_id, kb):
    return {t.name: t for t in build_tools(session, user_id, kb)}


def test_toolset_exposes_all_business_tools():
    tools = _by_name(seeded_session(), "C-marc-dubois", None)
    assert set(tools) == _EXPECTED


def test_get_order_is_bound_to_customer():
    tools = _by_name(seeded_session(), "C-marc-dubois", None)
    result = tools["get_order"].invoke({"order_id": "O-2024-0101"})
    assert result["status"] == "prepared"


def test_tool_enforces_isolation():
    # Marc's toolset must never reach Sophie's order O-2024-0107.
    tools = _by_name(seeded_session(), "C-marc-dubois", None)
    result = tools["get_order"].invoke({"order_id": "O-2024-0107"})
    assert result["error"] == "not_found_or_forbidden"


def test_tool_does_not_expose_user_id_argument():
    tools = _by_name(seeded_session(), "C-marc-dubois", None)
    schema_fields = set(tools["get_order"].args_schema.model_fields)
    assert "user_id" not in schema_fields
    assert "order_id" in schema_fields
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'velmo.agent_tools'`.

- [ ] **Step 3: Créer `src/velmo/agent_tools.py`**

```python
"""LLM-facing tool wrappers for the Velmo agent.

The business tool functions in `velmo.tools` take `session`/`user_id`/`kb` as
positional arguments. The LLM must never choose `user_id` (that would break
per-customer isolation), so `build_tools` closes over `session`/`user_id`/`kb`
and exposes to the model only the business parameters it may legitimately pick.

The wrappers are rebuilt per request (session/user_id change each turn); they
are never cached at module level. LangChain's `@tool` decorator builds a
pydantic args schema from each wrapper's signature and docstring.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from . import tools


def build_tools(session, user_id: str, kb) -> list[BaseTool]:
    """Build the per-request toolset bound to one authenticated customer."""

    @tool
    def get_order(order_id: str) -> dict:
        """Récupère le statut et le détail d'une commande du client.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
        """
        return tools.get_order(session, order_id, user_id)

    @tool
    def track_shipment(order_id: str) -> dict:
        """Donne le suivi transporteur et la date de livraison estimée.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
        """
        return tools.track_shipment(session, order_id, user_id)

    @tool
    def check_stock(product_ref: str, size: str) -> dict:
        """Indique si un maillot est disponible dans une taille donnée.

        Args:
            product_ref: Référence catalogue du maillot (ex. france-1998).
            size: Taille demandée (S, M, L, XL, XXL).
        """
        return tools.check_stock(session, product_ref, size)

    @tool
    def search_kb(query: str) -> dict:
        """Cherche une réponse dans la FAQ Velmo (frais, délais, retours...).

        Args:
            query: Question ou mots-clés à rechercher dans la FAQ.
        """
        return tools.search_kb(kb, query)

    @tool
    def update_order_item(order_id: str, new_size: str) -> dict:
        """Change la taille d'un article tant que la commande n'est pas expédiée.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
            new_size: Nouvelle taille (S, M, L, XL, XXL).
        """
        return tools.update_order_item(session, order_id, user_id, new_size)

    @tool
    def update_shipping_address(
        order_id: str, line1: str, city: str, zip_code: str, country: str
    ) -> dict:
        """Modifie l'adresse de livraison tant que la commande n'est pas expédiée.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
            line1: Numéro et rue.
            city: Ville.
            zip_code: Code postal.
            country: Pays.
        """
        address = {"line1": line1, "city": city, "zip": zip_code, "country": country}
        return tools.update_shipping_address(session, order_id, user_id, address)

    @tool
    def cancel_order(order_id: str) -> dict:
        """Annule une commande tant qu'elle n'est pas expédiée.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
        """
        return tools.cancel_order(session, order_id, user_id)

    @tool
    def create_return(order_id: str, reason: str) -> dict:
        """Ouvre une demande de retour/échange pour une commande livrée.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
            reason: Motif du retour indiqué par le client.
        """
        return tools.create_return(session, order_id, user_id, reason)

    @tool
    def trigger_refund(order_id: str, amount: float, reason: str) -> dict:
        """Rembourse une commande sous le plafond (50€), sinon escalade.

        Args:
            order_id: Identifiant de commande au format O-AAAA-NNNN.
            amount: Montant du remboursement en euros.
            reason: Motif du remboursement.
        """
        return tools.trigger_refund(session, order_id, user_id, amount, reason)

    @tool
    def escalate_to_human(reason: str, order_id: str | None = None) -> dict:
        """Passe la main à un conseiller humain (litige, cas complexe).

        Args:
            reason: Raison de l'escalade.
            order_id: Commande concernée, si applicable.
        """
        return tools.escalate_to_human(session, user_id, reason, order_id)

    return [
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
```

- [ ] **Step 4: Lancer le test pour le voir passer**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: add build_tools with per-customer closure binding"
```

---

## Task 4: agent_graph.py — le StateGraph à deux nœuds

**Files:**
- Create: `src/velmo/agent_graph.py`
- Modify: `tests/conftest.py` (ajout de la classe `ScriptedToolCallingChatModel`, sans toucher aux fixtures existantes)
- Test: `tests/test_agent_graph.py`

**Interfaces:**
- Consumes: `velmo.routing.run_deterministic`, `velmo.routing.SYSTEM_PROMPT`, `velmo.agent_tools.build_tools`, `velmo.llm.get_chat_model`.
- Produces:
  - `velmo.agent_graph.AgentState` — `TypedDict` avec `messages: Annotated[list[BaseMessage], add_messages]` et `matched: bool`.
  - `velmo.agent_graph.build_graph(session, user_id: str, kb, chat_model: BaseChatModel, context: str = "")` — renvoie un graphe LangGraph compilé.
  - `velmo.agent_graph.answer(session, user_id: str, kb, message: str, context: str = "", chat_model: BaseChatModel | None = None) -> str` — exécute un tour et renvoie le texte final.
  - `conftest.ScriptedToolCallingChatModel` — `FakeMessagesListChatModel` dont `bind_tools` renvoie self, pour scripter des tool calls déterministes.

- [ ] **Step 1: Ajouter le helper de test scripté à `conftest.py`**

Dans `tests/conftest.py`, ajouter l'import et la classe (ne rien retirer) :

```python
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel


class ScriptedToolCallingChatModel(FakeMessagesListChatModel):
    """Fake chat model that accepts bind_tools (returns itself) so it can drive
    `create_agent` with a scripted sequence of tool-calling messages.

    `FakeMessagesListChatModel` alone raises NotImplementedError on bind_tools,
    which `create_agent` calls internally.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedToolCallingChatModel":
        return self
```

- [ ] **Step 2: Écrire le test qui échoue**

Créer `tests/test_agent_graph.py` :

```python
"""Tests for the two-node agent graph (deterministic node + LLM node)."""

from __future__ import annotations

from conftest import ScriptedToolCallingChatModel, seeded_session
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from velmo.agent_graph import answer, build_graph


def test_deterministic_path_never_calls_llm():
    session = seeded_session()
    # This response would appear only if the LLM node ran; the regex path must win.
    model = ScriptedToolCallingChatModel(responses=[AIMessage(content="LLM_WAS_CALLED")])
    reply = answer(
        session, "C-marc-dubois", None,
        "Quel est le statut de ma commande O-2024-0101 ?", chat_model=model,
    )
    assert "prepared" in reply
    assert "LLM_WAS_CALLED" not in reply


def test_llm_path_returns_final_message():
    session = seeded_session()
    model = ScriptedToolCallingChatModel(
        responses=[AIMessage(content="Bonjour, comment puis-je vous aider ?")]
    )
    reply = answer(session, "C-marc-dubois", None, "Bonjour", chat_model=model)
    assert reply == "Bonjour, comment puis-je vous aider ?"


def test_llm_path_tool_call_respects_isolation():
    session = seeded_session()
    # No order id / keyword => deterministic returns None => LLM node.
    # Scripted model calls get_order on Sophie's order while acting for Marc.
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "get_order", "args": {"order_id": "O-2024-0107"}, "id": "c1"}],
        ),
        AIMessage(content="Désolé, aucune commande à votre nom."),
    ]
    model = ScriptedToolCallingChatModel(responses=responses)
    graph = build_graph(session, "C-marc-dubois", None, model)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Vérifie une commande pour moi")], "matched": False}
    )
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages
    assert "not_found_or_forbidden" in tool_messages[0].content
```

- [ ] **Step 3: Lancer le test pour le voir échouer**

Run: `uv run pytest tests/test_agent_graph.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'velmo.agent_graph'`.

- [ ] **Step 4: Créer `src/velmo/agent_graph.py`**

```python
"""Assembles the Velmo agent as a single LangGraph StateGraph.

Two nodes:
- deterministic_node: the regex fast path (velmo.routing). No LLM call.
- llm_node: a ReAct agent (langchain create_agent) with the business tools,
  reached only when the deterministic path matches nothing.

Both paths flow through the same graph, so a future checkpointer and future
guardrail nodes can be inserted here and apply uniformly to both. The graph is
compiled without a checkpointer for this chantier.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
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
    # No checkpointer for chantier 001 — the future memory chantier wires one here.
    return graph.compile()


def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    graph = build_graph(session, user_id, kb, chat_model, context)
    result = graph.invoke({"messages": [HumanMessage(content=message)], "matched": False})
    return result["messages"][-1].content
```

- [ ] **Step 5: Lancer le test pour le voir passer**

Run: `uv run pytest tests/test_agent_graph.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/velmo/agent_graph.py tests/conftest.py tests/test_agent_graph.py
git commit -m "feat: assemble two-node agent graph (deterministic + LLM tool-calling)"
```

---

## Task 5: intégration dans Agent + nettoyage du code mort

**Files:**
- Modify: `src/velmo/agent.py` (réécriture : `__init__`, `respond`, `build_default_agent` ; suppression de `_handle` et helpers)
- Modify: `src/velmo/llm.py` (suppression de `EchoLLM`, `AzureLLM`, `LLM`, `get_llm`)
- Modify: `tests/conftest.py` (fixtures : `chat_model=OfflineChatModel()`)
- Modify: `CLAUDE.md` (2 mentions de `EchoLLM`/`get_llm`)
- Test: `tests/acceptance/test_business.py` (inchangé) + tous les nouveaux tests

**Interfaces:**
- Consumes: `velmo.agent_graph.answer`, `velmo.llm.get_chat_model`, `velmo.llm.OfflineChatModel`.
- Produces:
  - `velmo.agent.Agent(chat_model, memory, guardrails, session=None, kb=None)` — le paramètre `llm` devient `chat_model`.
  - `velmo.agent.build_default_agent(session=None, kb=None) -> Agent`.

- [ ] **Step 1: Réécrire `src/velmo/agent.py`**

Remplacer l'intégralité du fichier par :

```python
"""Agent Velmo 2.0 : garde-fou d'entrée → mémoire → graphe (routage déterministe
+ nœud LLM outillé) → garde-fou de sortie → écriture mémoire.

`Agent.respond` orchestre le pipeline ; le raisonnement (routage regex + agent
LangGraph) vit dans `velmo.agent_graph`. La mémoire et les garde-fous de contenu
sont encore des stubs (chantiers suivants).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from . import agent_graph
from .guardrails import GuardrailEngine
from .memory import MemoryManager

DEFAULT_REFUSAL = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)


class Agent:
    """Assistant de support adossé au graphe (routage déterministe + LLM outillé)."""

    def __init__(
        self,
        chat_model: BaseChatModel | None,
        memory: MemoryManager,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
    ) -> None:
        self.chat_model = chat_model
        self.memory = memory
        self.guardrails = guardrails
        self.session = session
        self.kb = kb

    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            refusal = gate_in.refusal or DEFAULT_REFUSAL
            self.memory.write(user_id, message, refusal)
            return refusal

        context = self.memory.read(user_id, message).render()
        answer = agent_graph.answer(
            self.session, user_id, self.kb, message,
            context=context, chat_model=self.chat_model,
        )

        gate_out = self.guardrails.check_output(answer)
        if not gate_out.allowed:
            answer = gate_out.refusal or DEFAULT_REFUSAL

        self.memory.write(user_id, message, answer)
        return answer


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
        memory=MemoryManager(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=kb,
    )
```

- [ ] **Step 2: Retirer le code LLM mort de `src/velmo/llm.py`**

Dans `src/velmo/llm.py`, supprimer la classe `EchoLLM`, la classe `AzureLLM`, le `Protocol` `LLM`, la fonction `get_llm`, et l'import `from typing import Protocol` s'il n'est plus utilisé. Conserver uniquement : le docstring, les imports, `OfflineChatModel`, `get_chat_model`. Le fichier doit désormais ressembler à :

```python
"""Chat model factory: Azure AI Inference (Kimi-K2.6) and an offline fallback.

The Azure SDK import is deferred so the harness and tests run without the SDK
or a reachable endpoint. `get_chat_model` returns a LangChain `BaseChatModel`
usable directly by `create_agent`.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class OfflineChatModel(BaseChatModel):
    """Deterministic offline chat model (no tool calling).

    Returns a plain acknowledgement so `make chat` and the LLM fallback path
    work without Azure credentials.
    """

    @property
    def _llm_type(self) -> str:
        return "velmo-offline"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "OfflineChatModel":
        # No tool calling offline; the model simply acknowledges the message.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        text = last_human.content if last_human else ""
        message = AIMessage(content=f"[velmo] J'ai bien reçu : {text}")
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_chat_model() -> BaseChatModel:
    """Return the Azure chat model if configured, else the offline fallback."""
    if not os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        return OfflineChatModel()

    from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel

    return AzureAIOpenAIApiChatModel(
        endpoint=os.environ["AZURE_AI_INFERENCE_ENDPOINT"],
        credential=os.environ["AZURE_AI_INFERENCE_API_KEY"],
        model=os.environ.get("AZURE_AI_INFERENCE_MODEL", "Kimi-K2.6"),
    )
```

- [ ] **Step 3: Migrer les fixtures de `tests/conftest.py`**

Dans `tests/conftest.py` :
- remplacer `from velmo.llm import EchoLLM` par `from velmo.llm import OfflineChatModel` ;
- dans `build_reference_agent`, remplacer `llm=EchoLLM(),` par `chat_model=OfflineChatModel(),` ;
- dans `build_degraded_agent`, remplacer `llm=EchoLLM(),` par `chat_model=OfflineChatModel(),`.

Laisser intacts : `ScriptedToolCallingChatModel` (ajouté en Task 4), `AllowAllGuardrails`, les autres fixtures.

- [ ] **Step 4: Lancer les tests métier et nouveaux tests**

Run: `uv run pytest tests/acceptance/test_business.py tests/test_llm.py tests/test_routing.py tests/test_agent_tools.py tests/test_agent_graph.py -v`
Expected: tous PASS (7 + 3 + 4 + 4 + 3 = 21 tests).

- [ ] **Step 5: Vérifier qu'aucune référence morte ne subsiste**

Run: `uv run python -c "import velmo.agent, velmo.cli, velmo.agent_graph; print('imports ok')" && ! grep -rn "EchoLLM\|get_llm\|AzureLLM" src/velmo tests`
Expected: `imports ok` affiché, et le `grep` ne renvoie aucune ligne (code 1 → la commande globale réussit grâce au `!`).

- [ ] **Step 6: Mettre à jour `CLAUDE.md`**

Dans `CLAUDE.md`, remplacer la phrase (section « Le coeur tourne entièrement hors-ligne ») :

```
pour la FAQ, `EchoLLM` pour le LLM. Les intégrations réelles (Postgres, Chroma, Azure AI Inference) ne
```

par :

```
pour la FAQ, `OfflineChatModel` pour le LLM. Les intégrations réelles (Postgres, Chroma, Azure AI Inference) ne
```

et remplacer le paragraphe de la section « ### LLM (`src/velmo/llm.py`) » :

```
`get_llm()` retourne `AzureLLM` (Kimi-K2.6 via `langchain-azure-ai`, import différé) si
`AZURE_AI_INFERENCE_ENDPOINT` est défini, sinon `EchoLLM` (accusé de réception déterministe). Le LLM
n'est appelé qu'en dernier recours dans `Agent._handle` — la majorité des intentions métier sont
routées sans LLM.
```

par :

```
`get_chat_model()` retourne un `AzureAIOpenAIApiChatModel` (Kimi-K2.6 via `langchain-azure-ai`, import
différé) si `AZURE_AI_INFERENCE_ENDPOINT` est défini, sinon `OfflineChatModel` (accusé de réception
déterministe, sans tool-calling). L'agent est un `StateGraph` (`velmo.agent_graph`) : le nœud
déterministe (`velmo.routing`) route la majorité des intentions sans LLM, et ne bascule sur le nœud LLM
outillé (`create_agent` + `build_tools`) que lorsqu'aucune règle ne matche.
```

- [ ] **Step 7: Commit**

```bash
git add src/velmo/agent.py src/velmo/llm.py tests/conftest.py CLAUDE.md
git commit -m "feat: route Agent through the LangGraph agent, drop EchoLLM"
```

---

## Self-Review

**1. Spec coverage:**
- Single StateGraph, deterministic node + LLM node → Task 4. ✔
- Deterministic logic relocated unchanged → Task 2 (+ acceptance business tests unchanged, verified Task 5). ✔
- `Agent.respond` pipeline wrapper (guardrails → memory.read → graph → guardrails → memory.write) → Task 5. ✔
- Tools closed over session/user_id/kb, no user_id exposed → Task 3 (`test_tool_does_not_expose_user_id_argument`, `test_tool_enforces_isolation`). ✔
- `get_chat_model` + `OfflineChatModel` (offline, no tool calling) → Task 1. ✔
- `FakeMessagesListChatModel` scripté pour les tests → `ScriptedToolCallingChatModel`, Task 4. ✔
- Graphe sans checkpointer → Task 4 (`graph.compile()` nu, commentaire). ✔
- Memory context branché en entrée du graphe (même si vide) → Task 4 (`context` param) + Task 5 (`memory.read().render()`). ✔
- `memory.write` reste le point d'enregistrement → Task 5 (inchangé dans `respond`). ✔
- `EchoLLM`/`LLM`/`AzureLLM` retirés si morts → Task 5. ✔
- `db.py`/`tools/*.py` inchangés → aucune tâche ne les touche. ✔
- Nouveau `tests/test_agent_graph.py` (routage, tool-calling, isolation) → Task 4. ✔
- Critère « make chat sans credentials » → couvert par `OfflineChatModel` (Task 1) + pipeline (Task 5) ; validable manuellement via `make chat`.
- Écart dépendances (langchain en cœur) → documenté dans Global Constraints + Task 1.

**2. Placeholder scan:** aucun TBD/TODO ; chaque étape de code contient le code complet.

**3. Type consistency:** `run_deterministic(session, user_id, kb, message) -> str | None` (Task 2) consommé tel quel par `deterministic_node` (Task 4). `build_tools(session, user_id, kb) -> list[BaseTool]` (Task 3) consommé par `build_graph` (Task 4). `answer(session, user_id, kb, message, context="", chat_model=None) -> str` (Task 4) consommé par `Agent.respond` (Task 5). `get_chat_model`/`OfflineChatModel` (Task 1) consommés par Task 4/5. `ScriptedToolCallingChatModel` défini Task 4, utilisé Task 4. Noms d'outils cohérents entre Task 3 et les tests. Cohérent.
