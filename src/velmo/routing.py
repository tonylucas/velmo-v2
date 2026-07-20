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
from .tools.memory_tools import forget_user_data, inspect_user_memory
from .trace import Trace

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
    "frais de port",
    "frais de livraison",
    "délai",
    "delai",
    "politique de retour",
    "authenticit",
    "certificat",
    "paiement",
    "réassort",
    "reassort",
    "rétractation",
    "retractation",
    "entretien",
    "garantie",
    "remboursement sous",
    "conditions d'échange",
)

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
    match = re.search(
        r"(?:oubli\w*|supprim\w*|efface\w*)\s+(?:mon|ma|mes|le|la|les|l['’])?\s*(.+)", low
    )
    if not match:
        return None
    target = match.group(1)
    for phrase in ("je confirme", "c'est confirmé", "confirme", "oui je", "vas-y"):
        target = target.replace(phrase, "")
    return target.strip(" ,.;:!?'’\"") or None


def _handle_forget(store, user_id: str, low: str, confirmed: bool) -> str:
    is_global = any(h in low for h in _GLOBAL_FORGET_HINTS)
    target = None if is_global else _extract_forget_target(low)
    label = (
        "toutes vos informations"
        if is_global
        else (f"« {target} »" if target else "cette information")
    )
    if not confirmed:
        return (
            f"Vous souhaitez que j'oublie {label} ? Cette action est irréversible. "
            "Répondez « je confirme » pour valider."
        )
    result = forget_user_data(store, user_id, target)
    if result["action"] == "nothing_to_forget":
        return "Je n'ai trouvé aucune information de ce type à oublier."
    return f"C'est fait : j'ai oublié {label} ({result['count']} élément(s) supprimé(s))."


def run_deterministic(
    session, user_id: str, kb, message: str, store=None, *, trace: Trace | None = None
) -> str | None:
    """Route a message to a business tool by regex. Return the reply, or None
    when no deterministic intent matches (LLM fallback).

    A `trace` (demo UI) records which intent matched. The routing decision itself
    lives in `_route`, which names the intent it took.
    """
    if trace is None:
        reply, _ = _route(session, user_id, kb, message, store)
        return reply
    # Timed: the fast path runs the business tools, so this is where a
    # deterministic turn actually spends its milliseconds.
    with trace.timed("graph", "deterministic_node") as step:
        reply, intent = _route(session, user_id, kb, message, store, trace=trace)
        if reply is None:
            step.outcome = "no_match"
        else:
            step.outcome = "match"
            step.detail["intent"] = intent
    return reply


def _route(
    session,
    user_id: str,
    kb,
    message: str,
    store=None,
    *,
    trace: Trace | None = None,
) -> tuple[str | None, str | None]:
    """Return (reply, intent) for a message, or (None, None) when nothing matches."""
    low = message.lower()
    order = ORDER_RE.search(message)
    order_id = order.group(0) if order else None
    confirmed = any(c in low for c in _CONFIRM)

    if order_id and "annul" in low:
        return _confirm_or_act(
            confirmed,
            "annuler",
            order_id,
            lambda: tools.cancel_order(session, order_id, user_id),
            tool="cancel_order",
            trace=trace,
        ), "cancel_order"
    if order_id and "adresse" in low:
        return _confirm_or_act(
            confirmed,
            "modifier l'adresse de",
            order_id,
            lambda: tools.update_shipping_address(
                session, order_id, user_id, {"line1": "(à préciser)"}
            ),
            tool="update_shipping_address",
            trace=trace,
        ), "update_shipping_address"
    if (
        order_id
        and "taille" in low
        and any(w in low for w in ("chang", "modif", "tromp", "erreur"))
    ):
        size = SIZE_RE.search(message)
        new_size = size.group(1) if size else "M"
        return _confirm_or_act(
            confirmed,
            f"changer la taille (vers {new_size}) de",
            order_id,
            lambda: tools.update_order_item(session, order_id, user_id, new_size),
            tool="update_order_item",
            trace=trace,
        ), "update_order_item"
    if order_id and any(w in low for w in ("retour", "échange", "echange", "renvoyer")):
        return _confirm_or_act(
            confirmed,
            "ouvrir un retour pour",
            order_id,
            lambda: tools.create_return(session, order_id, user_id, "Demande client"),
            tool="create_return",
            trace=trace,
        ), "create_return"
    if order_id and "rembours" in low:
        amount_match = AMOUNT_RE.search(message)
        amount = float(amount_match.group(1).replace(",", ".")) if amount_match else 0.0
        return _confirm_or_act(
            confirmed,
            f"rembourser {amount:.0f}€ sur",
            order_id,
            lambda: tools.trigger_refund(session, order_id, user_id, amount, "Demande client"),
            tool="trigger_refund",
            trace=trace,
        ), "trigger_refund"

    if order_id and any(w in low for w in ("suivi", "colis", "livr", "transport", "track")):
        return _format_tracking(tools.track_shipment(session, order_id, user_id)), "track_shipment"
    if order_id:
        return _format_order(tools.get_order(session, order_id, user_id)), "order_status"

    if any(w in low for w in ("dispo", "stock", "reste", "en taille")):
        return _handle_stock(session, message, low), "stock_check"

    if any(k in low for k in _FAQ_KEYWORDS):
        return _format_kb(tools.search_kb(kb, message)), "faq"

    if store is not None and any(h in low for h in _INSPECT_HINTS):
        return inspect_user_memory(store, user_id), "inspect_memory"
    if store is not None and _FORGET_RE.search(low):
        return _handle_forget(store, user_id, low, confirmed), "forget"

    return None, None


def _confirm_or_act(
    confirmed: bool,
    label: str,
    order_id: str,
    action: Callable[[], dict],
    *,
    tool: str,
    trace: Trace | None = None,
) -> str:
    if not confirmed:
        return (
            f"Pour {label} la commande {order_id}, pouvez-vous confirmer ? "
            "Répondez « je confirme »."
        )
    result = action()
    if trace is not None:
        # Business tools return either {"error": ...} or {"action": ...} — never
        # both, and never an exception for an expected case. That convention is
        # what makes the verdict readable here rather than inside each tool.
        outcome = "error" if result.get("error") else str(result.get("action", "ok"))
        trace.add("tool", tool, outcome)
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
