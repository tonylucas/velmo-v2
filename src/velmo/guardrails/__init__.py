"""Input/output guardrails for the Velmo agent.

Stable public surface consumed by the agent and the acceptance suite.
"""

from __future__ import annotations

from .decision import CATEGORIES, Decision, Identity
from .engine import GuardrailEngine

__all__ = ["CATEGORIES", "Decision", "Identity", "GuardrailEngine"]
