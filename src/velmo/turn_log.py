"""In-process record of what ran during one ``Agent.respond`` turn.

Records which guardrail detectors fired, which graph nodes were traversed, which
business tools were called, which facts were injected and extracted — so the
Streamlit demo can show the machinery rather than assert it works, and so the
tests can assert on it synchronously.

Deliberately dependency-free (no Streamlit, no LangGraph, no guardrails import):
every stage of the pipeline takes an optional ``TurnLog`` and this module must
not depend on any of them. Recording is opt-in — when no ``TurnLog`` is passed
the pipeline behaves exactly as before and costs nothing.

Not to be confused with two neighbours that record different things:

- ``velmo.observability`` exports a Langfuse *trace* per turn: latency, tokens,
  cost and prompts, sent over the network, read after the fact. It sees the
  graph (via the LangChain callback handler) but is blind to the guardrails and
  the memory writes, which run outside it. A ``TurnLog`` is the reverse: local,
  synchronous, no credentials, and it spans the whole pipeline. This is also why
  ``Agent.respond`` builds one internally — ``_tool_signals`` reads the
  escalation and tool-error flags back out of it to attach them to the Langfuse
  span.
- ``GuardrailEngine.events`` stays the compliance journal and records metadata
  only.

A ``TurnLog`` is held in Streamlit's session state and never persisted.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# Pipeline stages, in the order a turn traverses them.
STAGES = ("guardrail_in", "memory", "graph", "tool", "guardrail_out")


@dataclass
class TurnLogStep:
    """One observed step of a turn."""

    stage: str
    name: str
    outcome: str
    detail: dict[str, object] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class TurnLog:
    """Ordered record of the steps taken during a single turn."""

    steps: list[TurnLogStep] = field(default_factory=list)

    def add(self, stage: str, name: str, outcome: str, **detail: object) -> TurnLogStep:
        """Record an instant step and return it, so the caller can refine it.

        Duration is not a parameter here: a `**detail` key named `duration_ms`
        would silently shadow it. Use `timed()` to measure a step instead.
        """
        step = TurnLogStep(stage=stage, name=name, outcome=outcome, detail=detail)
        self.steps.append(step)
        return step

    @contextmanager
    def timed(self, stage: str, name: str) -> Iterator[TurnLogStep]:
        """Record a step and time it; the body sets ``outcome``/``detail``.

        The step is appended up front and kept even if the body raises, so a
        failing backend leaves a visible step instead of vanishing from the panel.
        """
        step = self.add(stage, name, "pending")
        started = time.perf_counter()
        try:
            yield step
        finally:
            step.duration_ms = (time.perf_counter() - started) * 1000

    @property
    def path(self) -> str:
        """Which route the turn took — the panel's one-line summary."""
        for step in self.steps:
            if step.stage == "guardrail_in" and step.outcome == "block":
                return "bloqué"
        names = {step.name for step in self.steps if step.stage == "graph"}
        if "llm_node" in names:
            return "LLM"
        return "déterministe"

    @property
    def total_ms(self) -> float:
        return sum(step.duration_ms for step in self.steps)
