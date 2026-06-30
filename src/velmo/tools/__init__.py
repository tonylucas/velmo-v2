"""Outils métier de l'agent Velmo (accès Postgres + FAQ Chroma).

Chaque outil est une fonction documentée (découvrable par le LLM) qui encapsule
les règles métier : isolation par client, interdiction de modifier une commande
expédiée, plafond de remboursement, escalade.
"""

from __future__ import annotations

from .catalog import check_stock
from .escalation import escalate_to_human
from .kb import search_kb
from .orders import (
    cancel_order,
    get_order,
    track_shipment,
    update_order_item,
    update_shipping_address,
)
from .refunds import trigger_refund
from .returns import create_return

__all__ = [
    "get_order",
    "track_shipment",
    "check_stock",
    "search_kb",
    "update_order_item",
    "update_shipping_address",
    "cancel_order",
    "create_return",
    "trigger_refund",
    "escalate_to_human",
]
