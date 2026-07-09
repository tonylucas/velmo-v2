"""Tests for the short-term memory checkpointer factory."""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from velmo.memory.checkpointer import get_checkpointer


def test_offline_returns_in_memory_saver(monkeypatch):
    monkeypatch.delenv("DB_URL", raising=False)
    assert isinstance(get_checkpointer(), InMemorySaver)


def test_each_call_returns_a_fresh_saver(monkeypatch):
    # A fresh saver per call keeps per-agent conversations isolated in tests.
    monkeypatch.delenv("DB_URL", raising=False)
    assert get_checkpointer() is not get_checkpointer()
