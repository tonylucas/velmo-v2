"""Constantes et utilitaires partagés par les outils métier."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ..db import Order, OrderStatus

REFUND_CAP = 50.0
# Une commande n'est modifiable / annulable que tant qu'elle n'est pas partie.
MODIFIABLE_STATUSES = {OrderStatus.paid, OrderStatus.prepared}
RETURNABLE_STATUSES = {OrderStatus.delivered}

# Both spellings mean the same thing to a metric: `escalate` is a tool declining
# to act, `escalated` is escalate_to_human succeeding. Downstream reads one word.
ESCALATION_ACTIONS = frozenset({"escalate", "escalated"})

# `error` values a tool returns for a business/authorization verdict rather than
# a technical fault — the request was well-formed and reached the tool, which
# declined it on purpose. `not_found_or_forbidden` is `owned_order`'s isolation
# check (R3): a customer mistyping an order id, or probing someone else's, hits
# this on every read/write tool. `unknown_product` is `check_stock` rejecting a
# reference that does not exist. Neither is a system fault, so neither may count
# towards the technical tool-error rate.
BUSINESS_VERDICTS = frozenset({"not_found_or_forbidden", "unknown_product"})


def classify_result(result: dict[str, object]) -> str:
    """The outcome word for a tool result: a business verdict, "error", "escalate",
    or its action verb.

    Single source of truth so the deterministic path and the LLM path cannot
    drift apart: both escalation verbs normalize to "escalate", and a business
    verdict such as `not_found_or_forbidden` reports as itself rather than
    folding into "error" — "error" is reserved for genuine technical failure,
    which is what the tool-error metric is meant to measure.
    """
    error = result.get("error")
    if error:
        error_str = str(error)
        return error_str if error_str in BUSINESS_VERDICTS else "error"
    action = str(result.get("action", "ok"))
    return "escalate" if action in ESCALATION_ACTIONS else action


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def owned_order(session, order_id: str, user_id: str) -> Order | None:
    """Renvoie la commande si elle appartient bien au client, sinon None (isolation R3)."""
    order = session.get(Order, order_id)
    if order is None or order.customer_id != user_id:
        return None
    return order


def order_to_dict(order: Order) -> dict:
    return {
        "order_id": order.id,
        "status": order.status.value,
        "total": float(order.total),
        "shipping_address": order.shipping_address,
        "items": [
            {"item_id": it.id, "variant_id": it.variant_id, "size": it.size.value}
            for it in order.items
        ],
    }


__all__ = [
    "REFUND_CAP",
    "MODIFIABLE_STATUSES",
    "RETURNABLE_STATUSES",
    "ESCALATION_ACTIONS",
    "BUSINESS_VERDICTS",
    "classify_result",
    "new_id",
    "owned_order",
    "order_to_dict",
    "select",
]
