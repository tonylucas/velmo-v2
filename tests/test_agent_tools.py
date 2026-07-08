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
