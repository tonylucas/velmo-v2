"""get_tracer() picks a backend the way get_kb()/get_chat_model() do."""

from __future__ import annotations

import pytest

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
    # Agent.respond uses this to skip building an internal TurnLog offline.
    assert NoOpTracer().records is False


def test_a_noop_turn_offers_no_callbacks_and_swallows_end() -> None:
    turn = NoOpTracer().start_turn("C-marc-dubois", "bonjour")

    assert isinstance(turn, NoOpTurn)
    assert turn.callbacks == []
    assert turn.end(answer="salut", escalated=True) is None


def test_importing_the_module_does_not_import_langfuse() -> None:
    # The import must stay lazy: the core installs without the `obs` extra, and
    # the offline path must not pay for a heavy OpenTelemetry import.
    #
    # Run in a fresh subprocess rather than checking `sys.modules` in-process:
    # by the time this test runs, some other test in the suite (e.g. the ones
    # below that monkeypatch a fake `langfuse` module in) may already have put
    # "langfuse" into `sys.modules` for this interpreter — or the real package
    # may have been imported by an unrelated test that exercises `get_tracer()`
    # with credentials set. Either way this assertion would then pass or fail
    # purely by collection order rather than by what `import velmo.observability`
    # / `import velmo.agent` actually does. A subprocess starts with a clean
    # `sys.modules` every time, so the result depends only on the import graph.
    import subprocess
    import sys

    script = (
        "import sys\n"
        "import velmo.observability\n"
        "import velmo.agent\n"
        "assert 'langfuse' not in sys.modules, sorted(sys.modules)\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"
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
    # the turn_log stays useful.
    assert list(replacements) == ["gen_ai.completion.0.content"]
    assert "4111" not in replacements["gen_ai.completion.0.content"]
    assert "[REDACTED_CARD]" in replacements["gen_ai.completion.0.content"]


def test_clean_attributes_produce_no_patch() -> None:
    assert observability._redact_attributes({"gen_ai.completion.0.content": "Bonjour !"}) == {}


class _FakeSpan:
    def __init__(self, attributes: dict) -> None:
        self.attributes = attributes


class _FakeMaskParams:
    """Stands in for `langfuse.types.MaskOtelSpansParams`: `_mask_otel_spans`
    only reads `.spans`, so a minimal double is enough to exercise it directly
    without a live SDK export pipeline."""

    def __init__(self, spans: dict) -> None:
        self.spans = spans


def test_mask_otel_spans_redacts_the_offending_span() -> None:
    from langfuse.types import MaskOtelSpansResult

    params = _FakeMaskParams(
        {"span-1": _FakeSpan({"gen_ai.completion.0.content": "Carte 4111 1111 1111 1111."})}
    )

    result = observability._mask_otel_spans(params=params)

    assert isinstance(result, MaskOtelSpansResult)
    patch = result.span_patches["span-1"]
    assert "4111" not in patch.set_attributes["gen_ai.completion.0.content"]


def test_mask_otel_spans_fails_closed_on_a_masking_bug(monkeypatch) -> None:
    # Pinning the fix: a bug in the masking logic must never fall back to
    # exporting spans unredacted. Verified against the installed SDK
    # (`langfuse/_client/span_exporter.py`): a raised exception here makes the
    # exporter drop the whole batch (SUCCESS, nothing sent) — the failure mode
    # is "lose this batch of observability". A caught exception returning
    # `None` instead would hit `_apply_mask_otel_spans`'s "no patches needed"
    # branch and export every span **unredacted** — exactly backwards for a
    # privacy gate. So this hook must propagate, not swallow.
    def boom(_value: str) -> tuple[str, bool]:
        raise RuntimeError("scan_secrets exploded")

    monkeypatch.setattr(observability, "scan_secrets", boom)
    params = _FakeMaskParams({"span-1": _FakeSpan({"gen_ai.completion.0.content": "hello"})})

    with pytest.raises(RuntimeError, match="scan_secrets exploded"):
        observability._mask_otel_spans(params=params)


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


def test_langfuse_turn_end_closes_the_stack_even_when_update_current_span_raises(
    monkeypatch,
) -> None:
    # If update_current_span raises, the ExitStack must still close: otherwise
    # the OTel context (propagate_attributes + start_as_current_observation)
    # stays entered and bleeds into whatever runs next on this thread —
    # including the next turn on the same thread.
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    fake_langfuse = ModuleType("langfuse")
    propagate_cm = MagicMock()
    fake_langfuse.propagate_attributes = MagicMock(return_value=propagate_cm)  # type: ignore[attr-defined]
    fake_langchain = ModuleType("langfuse.langchain")
    fake_langchain.CallbackHandler = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    fake_langfuse.langchain = fake_langchain  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)

    client = MagicMock()
    span_cm = client.start_as_current_observation.return_value
    client.update_current_span.side_effect = RuntimeError("boom")
    turn = observability.LangfuseTurn(client, "pk-lf-test", "C-marc-dubois", "bonjour", "v1")

    with pytest.raises(RuntimeError, match="boom"):
        turn.end(answer="salut")

    # Both context managers entered by __init__ must have been exited, in
    # spite of the raise — that is what keeps the OTel context from leaking.
    span_cm.__exit__.assert_called_once()
    propagate_cm.__exit__.assert_called_once()


def test_langfuse_turn_record_retrieval_starts_a_retriever_observation(monkeypatch) -> None:
    # as_type="retriever" is the literal the whole chantier depends on: evaluators
    # and dashboards in Langfuse filter on observation type, so a regression to
    # as_type="span" would make the retrieved context invisible to them while
    # every other test still passed.
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
    observation = client.start_observation.return_value
    turn = observability.LangfuseTurn(client, "pk-lf-test", "C-marc-dubois", "bonjour", "v1")

    turn.record_retrieval("retrieve-memory", "bonjour", ["taille : fait du L"])

    client.start_observation.assert_called_once_with(
        name="retrieve-memory",
        as_type="retriever",
        input="bonjour",
        output=["taille : fait du L"],
    )
    observation.end.assert_called_once_with()


def test_a_noop_turn_swallows_a_recorded_retrieval() -> None:
    turn = NoOpTracer().start_turn("C-marc-dubois", "bonjour")

    assert turn.record_retrieval("retrieve-memory", "bonjour", ["taille : fait du L"]) is None


def test_the_memory_retrieval_span_name_is_stable() -> None:
    # Langfuse treats observation names as an API: dashboards, saved views and
    # evaluators all match on them, so a rename silently breaks them. Pinning the
    # value here makes an accidental rename a test failure rather than a silent
    # gap in someone's dashboard.
    assert observability.MEMORY_RETRIEVAL_NAME == "retrieve-memory"
