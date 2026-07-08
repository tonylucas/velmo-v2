"""Chat model factory: Azure AI Inference (Kimi-K2.6) and an offline fallback.

The Azure SDK import is deferred so the harness and tests run without the SDK
or a reachable endpoint. `get_chat_model` returns a LangChain `BaseChatModel`
usable directly by `create_agent`.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


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
