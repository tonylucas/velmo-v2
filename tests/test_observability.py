"""get_tracer() picks a backend the way get_kb()/get_chat_model() do."""

from __future__ import annotations

import velmo.observability as observability
from velmo.observability import NoOpTracer, NoOpTurn, get_tracer


def test_no_keys_gives_a_noop_tracer(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(get_tracer(), NoOpTracer)


def test_one_key_alone_is_not_enough(monkeypatch) -> None:
    # A half-configured environment must degrade, not raise: the demo has to keep
    # answering customers even when observability is misconfigured.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(get_tracer(), NoOpTracer)


def test_the_noop_tracer_declares_that_it_records_nothing() -> None:
    # Agent.respond uses this to skip building an internal Trace offline.
    assert NoOpTracer().records is False


def test_a_noop_turn_offers_no_callbacks_and_swallows_end() -> None:
    turn = NoOpTracer().start_turn("C-marc-dubois", "bonjour")

    assert isinstance(turn, NoOpTurn)
    assert turn.callbacks == []
    assert turn.end(answer="salut", escalated=True) is None


def test_importing_the_module_does_not_import_langfuse() -> None:
    # The import must stay lazy: the core installs without the `obs` extra, and
    # the offline path must not pay for a heavy OpenTelemetry import.
    import sys

    assert "langfuse" not in sys.modules
    assert observability.__name__ == "velmo.observability"


def test_exported_attributes_are_redacted() -> None:
    # Defence in depth: respond() masks the INPUT, but the LangChain handler
    # captures the raw LLM COMPLETION, and check_output only rejects a leak
    # after the fact. This is the last gate before data leaves the process.
    replacements = observability._redact_attributes(
        {
            "gen_ai.completion.0.content": "Le remboursement ira sur 4111 1111 1111 1111.",
            "gen_ai.prompt.0.content": "Où en est ma commande O-2024-0101 ?",
            "langfuse.observation.type": "generation",
            "token.count": 42,
        }
    )

    # Only the offending attribute is patched; the rest is left untouched so
    # the trace stays useful.
    assert list(replacements) == ["gen_ai.completion.0.content"]
    assert "4111" not in replacements["gen_ai.completion.0.content"]
    assert "[REDACTED_CARD]" in replacements["gen_ai.completion.0.content"]


def test_clean_attributes_produce_no_patch() -> None:
    assert observability._redact_attributes({"gen_ai.completion.0.content": "Bonjour !"}) == {}


def test_langfuse_turn_end_is_idempotent(monkeypatch) -> None:
    # Agent.respond's error-closing `finally` guard always calls end() a
    # second time, even on the normal path. A second call must be a clean
    # no-op: it must not touch the client again, which by then could be
    # current for a completely different span.
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    fake_langfuse = ModuleType("langfuse")
    fake_langfuse.propagate_attributes = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_langchain = ModuleType("langfuse.langchain")
    fake_langchain.CallbackHandler = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_langfuse.langchain = fake_langchain  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)

    client = MagicMock()
    turn = observability.LangfuseTurn(client, "pk-lf-test", "C-marc-dubois", "bonjour", "v1")

    turn.end(answer="salut")
    turn.end(answer="should be ignored", error=True)

    assert client.update_current_span.call_count == 1
    assert client.flush.call_count == 1
