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
