"""Unit tests for the long-term memory tools."""

from __future__ import annotations

from velmo.memory.fact_store import LocalFactStore
from velmo.tools.memory_tools import (
    forget_user_data,
    inspect_user_memory,
    remember_fact,
)


def test_remember_fact_persists():
    store = LocalFactStore()
    result = remember_fact(store, "u1", "profile", "pointure", "L")
    assert result["action"] == "remembered"
    assert "pointure" in inspect_user_memory(store, "u1")


def test_forget_target_reports_count():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    result = forget_user_data(store, "u1", target="adresse")
    assert result == {"action": "forgotten", "count": 1}
    assert "Lilas" not in inspect_user_memory(store, "u1")


def test_forget_nothing_matching():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    assert forget_user_data(store, "u1", target="adresse") == {"action": "nothing_to_forget"}


def test_forget_all():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    assert forget_user_data(store, "u1", target=None) == {"action": "forgotten", "count": 2}


def test_inspect_empty_memory():
    store = LocalFactStore()
    assert "aucune information" in inspect_user_memory(store, "u1").lower()


def test_inspect_lists_all_facts():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "preference", "tutoiement", "oui")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    summary = inspect_user_memory(store, "u1")
    assert "L" in summary
    assert "tutoiement" in summary
    assert "O-2024-0101" in summary
