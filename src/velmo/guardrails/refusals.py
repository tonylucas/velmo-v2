"""French refusal messages shown to the customer when a guardrail blocks.

Customer-facing copy stays in French (product language); identifiers stay English.
"""

from __future__ import annotations

_GENERIC = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)

REFUSALS: dict[str, str] = {
    "hate": "Je ne peux pas répondre à des propos haineux. Je suis là pour vous aider sur vos commandes Velmo.",
    "violence": "Je ne peux pas donner suite à des propos violents. Parlons plutôt de votre commande.",
    "sexual": "Je ne peux pas traiter de contenu à caractère sexuel. Je reste dispo pour le support Velmo.",
    "pii": "Pour votre sécurité, je ne peux pas manipuler ces données sensibles ici.",
    "out_of_scope": "Cette demande sort du support Velmo (estimation, revente, conseil juridique ou médical). Je peux vous aider sur vos commandes, livraisons et retours.",
    "prompt_injection": "Je ne peux pas modifier mes consignes de sécurité. Je reste à votre disposition pour le support Velmo.",
    "secret_leak": "Je ne peux pas divulguer d'informations techniques internes. Je peux vous aider sur vos commandes Velmo.",
}


def refusal_for(category: str | None) -> str:
    """Return the French refusal for a category, or a generic fallback."""
    if category is None:
        return _GENERIC
    return REFUSALS.get(category, _GENERIC)
