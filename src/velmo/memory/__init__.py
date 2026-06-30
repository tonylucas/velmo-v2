"""Mémoire de l'agent Velmo : contexte court terme et mémoire long terme.

Surface publique stable consommée par l'agent et la suite d'acceptance.
L'implémentation interne (court terme, long terme, orchestration) est à construire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Turn = tuple[str, str]  # (role, content)


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

    def __init__(self, *, token_budget: int = 2000) -> None:
        self.token_budget = token_budget

    def read(self, user_id: str, message: str) -> MemoryContext:
        """Reconstitue le contexte mémoire pertinent pour `message`."""
        return MemoryContext()

    def write(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """Met à jour la mémoire à partir d'un échange."""
        return None

    def remember_fact(self, user_id: str, key: str, value: str) -> None:
        """Persiste un fait durable sur l'utilisateur."""
        return None

    def forget(self, user_id: str, target: str) -> int:
        """Supprime les souvenirs correspondant à `target`. Renvoie le nombre supprimé."""
        return 0

    def inspect(self, user_id: str) -> dict:
        """Renvoie l'état mémoire d'un utilisateur (faits + souvenirs épisodiques)."""
        return {"facts": {}, "episodic": []}
