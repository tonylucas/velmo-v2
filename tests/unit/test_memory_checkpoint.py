"""Tests unitaires — fenêtre courte (src/velmo/memory/checkpoint.py)."""

from __future__ import annotations

from velmo.memory import checkpoint


def test_append_and_read_history():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-1", "bonjour", "salut")
    history = checkpoint.get_history(graph, "unit-user-1")
    assert [(m.type, m.content) for m in history] == [("human", "bonjour"), ("ai", "salut")]


def test_history_isolated_by_user():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-a", "msg a", "reponse a")
    checkpoint.append_turn(graph, "unit-user-b", "msg b", "reponse b")
    assert [m.content for m in checkpoint.get_history(graph, "unit-user-a")] == [
        "msg a",
        "reponse a",
    ]
    assert [m.content for m in checkpoint.get_history(graph, "unit-user-b")] == [
        "msg b",
        "reponse b",
    ]


def test_remove_messages_by_id():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    checkpoint.append_turn(graph, "unit-user-remove", "a supprimer", "reponse")
    history = checkpoint.get_history(graph, "unit-user-remove")
    target_id = history[0].id
    checkpoint.remove_messages(graph, "unit-user-remove", [target_id])
    remaining = checkpoint.get_history(graph, "unit-user-remove")
    assert [m.content for m in remaining] == ["reponse"]


def test_empty_history_for_unknown_user():
    graph = checkpoint.build_history_graph(checkpoint.build_checkpointer())
    assert checkpoint.get_history(graph, "unit-user-never-seen") == []
