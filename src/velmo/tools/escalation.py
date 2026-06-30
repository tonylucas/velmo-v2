"""Outil d'escalade vers un agent humain."""

from __future__ import annotations

from ..db import Escalation
from ._common import new_id


def escalate_to_human(session, customer_id: str, reason: str, order_id: str | None = None) -> dict:
    """Passe la main à un humain (litige, montant élevé, commande expédiée)."""
    escalation_id = new_id("esc")
    session.add(
        Escalation(id=escalation_id, customer_id=customer_id, order_id=order_id, reason=reason)
    )
    session.commit()
    return {"action": "escalated", "escalation_id": escalation_id, "reason": reason}
