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
        preference_facts = facts.preferences(self._collection, user_id)
        episodic = facts.search(self._collection, user_id, message, fact_type="episodic_excerpt")
        return MemoryContext(history=history, facts=preference_facts, episodic=episodic)

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

    def inspect(self, user_id: str) -> dict:
        """Renvoie l'état mémoire d'un utilisateur (faits + souvenirs épisodiques)."""
        entries = facts.all_facts(self._collection, user_id)
        facts_by_key = {e["key"]: e["content"] for e in entries if e.get("key")}
        episodic = [e["content"] for e in entries if not e.get("key")]
        return {"facts": facts_by_key, "episodic": episodic}
