"""Clients LLM : Azure AI Inference (Kimi-K2.6) et repli local hors-ligne.

L'import du SDK Azure est différé pour que le harness démarre et que les tests
tournent sans dépendre du SDK ni d'un endpoint joignable.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class LLM(Protocol):
    """Interface minimale d'un client de complétion."""

    def invoke(self, system: str, context: str, message: str) -> str: ...


class EchoLLM:
    """Repli déterministe et hors-ligne : renvoie un accusé de réception.

    Permet au harness de conversation de démarrer sans identifiants Azure.
    """

    def invoke(self, system: str, context: str, message: str) -> str:
        return f"[velmo] J'ai bien reçu : {message}"


class AzureLLM:
    """Adapte le modèle de chat Azure AI Inference à l'interface `LLM`."""

    def __init__(self, model) -> None:
        self._model = model

    def invoke(self, system: str, context: str, message: str) -> str:
        messages = [{"role": "system", "content": system}]
        if context:
            messages.append({"role": "system", "content": f"Mémoire:\n{context}"})
        messages.append({"role": "user", "content": message})
        return self._model.invoke(messages).content


def get_llm() -> LLM:
    """Construit le client Azure si configuré, sinon le repli `EchoLLM`."""
    if not os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        return EchoLLM()

    from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel

    model = AzureAIOpenAIApiChatModel(
        endpoint=os.environ["AZURE_AI_INFERENCE_ENDPOINT"],
        credential=os.environ["AZURE_AI_INFERENCE_API_KEY"],
        model=os.environ.get("AZURE_AI_INFERENCE_MODEL", "Kimi-K2.6"),
    )
    return AzureLLM(model)


class OfflineChatModel(BaseChatModel):
    """Deterministic offline chat model (no tool calling).

    Returns a plain acknowledgement so `make chat` and the LLM fallback path
    work without Azure credentials.
    """

    @property
    def _llm_type(self) -> str:
        return "velmo-offline"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "OfflineChatModel":
        # No tool calling offline; the model simply acknowledges the message.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        text = last_human.content if last_human else ""
        message = AIMessage(content=f"[velmo] J'ai bien reçu : {text}")
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_chat_model() -> BaseChatModel:
    """Return the Azure chat model if configured, else the offline fallback."""
    if not os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        return OfflineChatModel()

    from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel

    return AzureAIOpenAIApiChatModel(
        endpoint=os.environ["AZURE_AI_INFERENCE_ENDPOINT"],
        credential=os.environ["AZURE_AI_INFERENCE_API_KEY"],
        model=os.environ.get("AZURE_AI_INFERENCE_MODEL", "Kimi-K2.6"),
    )
