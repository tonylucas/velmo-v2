"""Tests for the chat model factory and the offline fallback."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.llm import OfflineChatModel, get_chat_model


def test_offline_model_echoes():
    model = OfflineChatModel()
    reply = model.invoke([HumanMessage(content="Bonjour")])
    assert reply.content.startswith("[velmo]")
    assert "Bonjour" in reply.content


def test_offline_model_bind_tools_returns_self():
    model = OfflineChatModel()
    assert model.bind_tools([]) is model


def test_get_chat_model_offline_without_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_AI_INFERENCE_ENDPOINT", raising=False)
    assert isinstance(get_chat_model(), OfflineChatModel)
