"""Per-turn execution trace for the demo UI.

Records what actually ran during one ``Agent.respond`` turn — which guardrail
detectors fired, which graph nodes were traversed, which business tools were
called, which facts were injected and extracted — so the Streamlit demo can show
the machinery rather than assert it works.

Deliberately dependency-free (no Streamlit, no LangGraph, no guardrails import):
every stage of the pipeline takes an optional ``Trace`` and this module must not
depend on any of them. Tracing is opt-in — when no ``Trace`` is passed the
pipeline behaves exactly as before and costs nothing.

Scope note: this is a *local demo* aid, held in Streamlit's session state and
never persisted. It is not ``GuardrailEngine.events``, which stays the
compliance journal and records metadata only.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# Pipeline stages, in the order a turn traverses them.
STAGES = ("guardrail_in", "memory", "graph", "tool", "guardrail_out")


@dataclass
class TraceStep:
    """One observed step of a turn."""

    stage: str
    name: str
    outcome: str
    detail: dict[str, object] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class Trace:
    """Ordered record of the steps taken during a single turn."""

    steps: list[TraceStep] = field(default_factory=list)

    def add(self, stage: str, name: str, outcome: str, **detail: object) -> TraceStep:
        """Record an instant step and return it, so the caller can refine it.

        Duration is not a parameter here: a `**detail` key named `duration_ms`
        would silently shadow it. Use `timed()` to measure a step instead.
        """
        step = TraceStep(stage=stage, name=name, outcome=outcome, detail=detail)
        self.steps.append(step)
        return step

    @contextmanager
    def timed(self, stage: str, name: str) -> Iterator[TraceStep]:
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
