"""Production observability: one Langfuse trace per conversational turn.

Same seam as `get_kb()` / `get_chat_model()` / `get_fact_store()`: the real
backend when the environment carries credentials, a no-op otherwise. Without
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` the whole test suite runs on
`NoOpTracer` and a turn costs two method calls.

Cost and token usage are only visible to the LangChain callback handler, which
is why `Turn` exposes `callbacks` for the graph to consume rather than timing
the turn itself. Latency and volume come from the span; the guardrail category,
escalation and tool errors are handed over as metadata by `Agent.respond`.

Privacy: callers must pass the *masked* message. Nothing here re-reads the raw
input, and a turn blocked by the input guardrail carries no content at all.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import ExitStack
from typing import Any, Protocol

from .guardrails.detectors import scan_secrets

DEFAULT_HOST = "https://cloud.langfuse.com"

# Verb-first and free of dynamic values: Langfuse treats observation names like
# an API — dashboards, saved views and evaluators all match on them, so a rename
# silently breaks them and a name carrying an id explodes their cardinality.
TURN_SPAN_NAME = "handle-turn"


class Turn(Protocol):
    """One traced turn, opened by `Tracer.start_turn` and closed by `end`."""

    callbacks: list[Any]

    def end(self, *, answer: str, **metadata: Any) -> None: ...


class Tracer(Protocol):
    """Backend that turns a conversational turn into an observation."""

    @property
    def records(self) -> bool:
        """Whether turns actually go anywhere. False lets callers skip the work
        of building the metadata this backend would only discard."""

    def start_turn(self, user_id: str, message: str) -> Turn: ...


class NoOpTurn:
    """A turn that records nothing and costs nothing."""

    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def end(self, *, answer: str, **metadata: Any) -> None:
        return None


class NoOpTracer:
    """Offline default: no credentials, no export, behaviour unchanged."""

    records = False

    def start_turn(self, user_id: str, message: str) -> Turn:
        return NoOpTurn()


class LangfuseTurn:
    """A turn exported to Langfuse.

    Opens a span plus the trace-level attributes and holds them in an ExitStack
    so `end` closes both in the right order. `callbacks` carries the LangChain
    handler that attributes token usage — and therefore cost — to this span.
    """

    records = True

    def __init__(
        self, client: Any, public_key: str, user_id: str, message: str, version: str
    ) -> None:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler

        self._client = client
        self._stack = ExitStack()
        self._stack.enter_context(
            # One trace per turn, one session per conversation — the structure
            # Langfuse prescribes for chatbots, and what makes "cost per
            # conversation" a query rather than a job.
            propagate_attributes(user_id=user_id, session_id=user_id, version=version)
        )
        self._stack.enter_context(
            # The root observation's input/output become the trace's: the docs
            # single these out as what reviewers and evaluators actually read,
            # so they are the customer message and the assistant reply, not a
            # raw payload.
            client.start_as_current_observation(name=TURN_SPAN_NAME, as_type="span", input=message)
        )
        # Passed explicitly: CallbackHandler resolves its client through
        # get_client(public_key=...), so naming the key pins it to the client we
        # built — the one carrying the masking hook.
        self.callbacks: list[Any] = [CallbackHandler(public_key=public_key)]

    def end(self, *, answer: str, **metadata: Any) -> None:
        # The metadata lands on the root span: the v4 SDK has no
        # `update_current_trace`, and these values are only known now.
        self._client.update_current_span(output=answer, metadata=metadata)
        self._stack.close()
        self._client.flush()


class LangfuseTracer:
    """Langfuse-backed tracer. Only built when credentials are present."""

    records = True

    def __init__(self, client: Any, public_key: str, version: str) -> None:
        self._client = client
        self._public_key = public_key
        self._version = version

    def start_turn(self, user_id: str, message: str) -> Turn:
        return LangfuseTurn(self._client, self._public_key, user_id, message, self._version)


def _redact_attributes(attributes: Mapping[str, Any]) -> dict[str, str]:
    """String attributes that carried a secret, with it redacted.

    Kept pure and free of any Langfuse import so it is testable offline — the
    export hook below is a thin wrapper around it.
    """
    replacements: dict[str, str] = {}
    for key, value in attributes.items():
        if isinstance(value, str):
            masked, found = scan_secrets(value)
            if found:
                replacements[key] = masked
    return replacements


def _mask_otel_spans(*, params: Any) -> Any:
    """Redact secrets from span attributes just before they leave the process.

    Defence in depth. `Agent.respond` masks the *input* before anything
    downstream sees it, but the LangChain handler captures the raw LLM
    *completion*, and `check_output` only rejects a leak after the fact — by
    which time the generation is already on the span. This hook is the last gate.

    Never raises: Langfuse drops the entire export batch on an exception, so a
    masking bug would silently cost observability rather than leak.
    """
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    try:
        patches = {}
        for identifier, span in params.spans.items():
            replacements = _redact_attributes(span.attributes)
            if replacements:
                patches[identifier] = OtelSpanPatch(set_attributes=replacements)
        return MaskOtelSpansResult(span_patches=patches)
    except Exception:
        return None


def get_tracer() -> Tracer:
    """Return the Langfuse tracer when configured, the no-op tracer otherwise.

    Both keys are required: a half-configured environment degrades to no-op
    rather than raising, so a misconfiguration never stops the agent answering.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not (public_key and secret_key):
        return NoOpTracer()
    try:
        from langfuse import Langfuse
    except ImportError:
        return NoOpTracer()

    # Imported here, not at module scope: `velmo.mlops` pulls in the eval suites,
    # which import the agent — which imports this module. Deferring keeps the
    # cycle from ever forming, and offline runs never reach this line.
    from .mlops.version import current_version

    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=os.getenv("LANGFUSE_HOST", DEFAULT_HOST),
        mask_otel_spans=_mask_otel_spans,
    )
    # Resolved once per process: current_version() shells out to `git describe`,
    # far too costly to repeat on every turn.
    return LangfuseTracer(client, public_key, current_version())
