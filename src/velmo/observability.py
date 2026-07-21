"""Production observability: one Langfuse trace per conversational turn, and
the Langfuse-managed system prompt those turns run against.

Same seam as `get_kb()` / `get_chat_model()` / `get_fact_store()`: the real
backend when the environment carries credentials, a no-op otherwise. Without
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` the whole test suite runs on
`NoOpTracer` and a turn costs two method calls; `Tracer.get_prompt` likewise
falls back to the literal text with no network call.

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
from contextlib import AbstractContextManager, ExitStack, nullcontext
from typing import Any, Protocol

from .guardrails.detectors import scan_secrets

DEFAULT_HOST = "https://cloud.langfuse.com"

# Verb-first and free of dynamic values: Langfuse treats observation names like
# an API — dashboards, saved views and evaluators all match on them, so a rename
# silently breaks them and a name carrying an id explodes their cardinality.
TURN_SPAN_NAME = "handle-turn"

# The memory RAG step, named by the action it performs. Same low-cardinality rule
# as TURN_SPAN_NAME: an evaluator or a saved view that matches on this name breaks
# silently if it changes, so it is pinned by a test.
MEMORY_RETRIEVAL_NAME = "retrieve-memory"

# Lowercase, hyphenated, feature-scoped — the langfuse skill's prompt-naming
# convention.
SYSTEM_PROMPT_NAME = "velmo-support-system"

# The literal prompt text: the offline default, and the `fallback=` Langfuse
# resolves to if the managed prompt is unreachable. One string, so the two
# paths can never drift apart.
SYSTEM_PROMPT_FALLBACK = (
    "Tu es l'assistant de support de Velmo, boutique de maillots de foot collector. "
    "Tu traites la gestion de commandes de niveau 1 avec courtoisie et précision."
)


class SystemPrompt(Protocol):
    """A compiled system prompt: Langfuse-managed in prod, the literal
    fallback text offline — same seam as `Tracer`/`Turn`.

    `link()` wraps the LLM call so the resulting generation is attributed to
    this prompt's name and version in Langfuse (see prompt-management ->
    link-to-traces). It is a no-op offline, where there is no trace to
    attribute it to.
    """

    def compile(self) -> str: ...

    def link(self) -> AbstractContextManager[None]: ...


class LiteralPrompt:
    """The offline default, and what `Agent`/`agent_graph` fall back to when
    no `prompt=` is given."""

    def __init__(self, text: str) -> None:
        self._text = text

    def compile(self) -> str:
        return self._text

    def link(self) -> AbstractContextManager[None]:
        return nullcontext()


class _LangfusePrompt:
    """Wraps a `TextPromptClient`, fetched once per `LangfuseTracer` lifetime
    (the SDK itself caches the underlying API call, `cache_ttl_seconds`)."""

    def __init__(self, prompt: Any) -> None:
        self._prompt = prompt

    def compile(self) -> str:
        # `_prompt` stays `Any` (see __init__): calling `str()` here, not just
        # trusting the SDK's declared return type, is what makes this a `str`
        # under mypy strict without importing `TextPromptClient` at module
        # scope, which would pull `langfuse` into the offline import graph.
        return str(self._prompt.compile())

    def link(self) -> AbstractContextManager[None]:
        from langfuse import propagate_attributes

        # The recommended hook for auto-instrumented generations (here, the
        # LangChain CallbackHandler via create_agent): we never construct the
        # GENERATION observation ourselves, so there is no `prompt=` kwarg to
        # pass directly — propagate_attributes attributes it to whichever
        # generation the callback handler opens next.
        return propagate_attributes(prompt=self._prompt)


class Turn(Protocol):
    """One traced turn, opened by `Tracer.start_turn` and closed by `end`."""

    callbacks: list[Any]

    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        """Record one RAG retrieval as a child observation of this turn.

        `documents` is the retrieved context exactly as the model received it, so
        an evaluator scoring faithfulness judges what the model actually saw. An
        empty list is still worth recording so the sampling stays consistent —
        but it is not a diagnosis of an off-topic answer: it is the normal state
        of any user with no durable facts stored yet, including one whose turn
        is fully and correctly grounded in the FAQ instead. Callers scoring
        faithfulness must treat an empty context as not-applicable, not as zero.

        Must be called before `end()`: the observation nests under the turn's
        span, and `end` closes that span (along with the rest of the turn's
        `ExitStack`) — a call made afterward would attach to whatever context
        happens to be current instead, not to this turn."""
        ...

    def end(self, *, answer: str, **metadata: Any) -> None:
        """Close the turn. Must be idempotent: `Agent.respond` wraps the traced
        body in `try/finally` and unconditionally calls `end` again there, so a
        raise can never leave a span open — every implementation must tolerate
        a repeated call as a no-op."""
        ...


class Tracer(Protocol):
    """Backend that turns a conversational turn into an observation, and vends
    the system prompt generations in that turn should be attributed to."""

    @property
    def records(self) -> bool:
        """Whether turns actually go anywhere. False lets callers skip the work
        of building the metadata this backend would only discard."""

    def start_turn(self, user_id: str, message: str) -> Turn: ...

    def get_prompt(self, name: str, *, fallback: str) -> SystemPrompt:
        """The named prompt, Langfuse-managed in prod, `fallback` offline."""
        ...


class NoOpTurn:
    """A turn that records nothing and costs nothing."""

    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        return None

    def end(self, *, answer: str, **metadata: Any) -> None:
        return None


class NoOpTracer:
    """Offline default: no credentials, no export, behaviour unchanged."""

    records = False

    def start_turn(self, user_id: str, message: str) -> Turn:
        return NoOpTurn()

    def get_prompt(self, name: str, *, fallback: str) -> SystemPrompt:
        return LiteralPrompt(fallback)


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
        self._ended = False
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

    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        # as_type="retriever" is not decoration: evaluators and dashboards filter
        # on observation type, so a retrieval typed as a plain span is invisible
        # to them. The observation nests under the turn's span automatically —
        # __init__ already entered start_as_current_observation.
        observation = self._client.start_observation(
            name=name, as_type="retriever", input=query, output=documents
        )
        observation.end()

    def end(self, *, answer: str, **metadata: Any) -> None:
        # Idempotent: a second call (e.g. the `finally` guard in Agent.respond
        # after the normal path already closed the turn) must be a clean no-op
        # rather than touching whatever span happens to be current by then.
        if self._ended:
            return
        self._ended = True
        # The stack must close no matter what: if update_current_span raises,
        # leaving the ExitStack open would leak the OTel context (propagate_attributes
        # + start_as_current_observation) into whatever runs next on this thread —
        # including the *next* turn, which would then be misattributed to this span.
        try:
            # The metadata lands on the root span: the v4 SDK has no
            # `update_current_trace`, and these values are only known now.
            self._client.update_current_span(output=answer, metadata=metadata)
        finally:
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

    def get_prompt(self, name: str, *, fallback: str) -> SystemPrompt:
        # label="production" is already the server-side default when no
        # version/label is given, but the langfuse skill recommends passing
        # it explicitly rather than relying on that default holding.
        prompt = self._client.get_prompt(name, label="production", fallback=fallback)
        return _LangfusePrompt(prompt)


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

    Deliberately lets exceptions propagate — do not add a broad `except` here.
    Verified against the installed SDK (`langfuse/_client/span_exporter.py`,
    `_apply_mask_otel_spans`/`export`): if this function raises, the exporter
    catches it, logs it, and returns `SpanExportResult.SUCCESS` from `export()`
    *without* ever calling the underlying exporter — the batch is dropped,
    unsent. But if this function *returns `None`* instead (e.g. a bare
    `except: return None`), that hits a different, documented branch
    (`langfuse/types.py`, `MaskOtelSpansResult`): `_apply_mask_otel_spans`
    treats a `None` result as "no patches needed" and the batch is exported
    **unredacted**. So catching here and returning `None` would turn this from
    a privacy gate into a pass-through on exactly the failure it exists to
    guard against. Raising keeps the only failure mode "lose this batch of
    observability", never "leak a secret".
    """
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        replacements = _redact_attributes(span.attributes)
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    return MaskOtelSpansResult(span_patches=patches)


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
