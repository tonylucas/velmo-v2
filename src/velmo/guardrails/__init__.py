"""Input/output guardrails for the Velmo agent.

Stable public surface consumed by the agent and the acceptance suite. The engine
is assembled in engine.py; this module re-exports the stable names.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decision import CATEGORIES, Decision, Identity

__all__ = ["CATEGORIES", "Decision", "Identity", "GuardrailEngine"]


@dataclass
class GuardrailEngine:
    """Temporary no-op stub, replaced by engine.GuardrailEngine in Task 5."""

    events: list[dict] = field(default_factory=list)

    def check_input(self, message: str) -> Decision:
        return Decision(allowed=True, action="allow")

    def check_output(self, text: str) -> Decision:
        return Decision(allowed=True, action="allow")
