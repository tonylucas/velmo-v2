"""Test unitaire — traçabilité de la mémoire (R6)."""

from __future__ import annotations

from velmo.memory import MemoryManager


def test_inspect_lists_facts_and_episodic_entries():
    mm = MemoryManager()
    user = "unit-inspect"
    mm.remember_fact(user, "pointure", "L")
    mm.remember_fact(user, "clubs", "OM et Bresil")

    result = mm.inspect(user)
    assert result["facts"]["pointure"] == "pointure: L"
    assert result["facts"]["clubs"] == "clubs: OM et Bresil"


def test_inspect_omits_forgotten_facts():
    mm = MemoryManager()
    user = "unit-inspect-forget"
    mm.remember_fact(user, "adresse", "12 rue des Lilas")
    mm.forget(user, "adresse")

    result = mm.inspect(user)
    assert "adresse" not in result["facts"]
