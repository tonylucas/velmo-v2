"""Pure guardrail types shared across detectors and the engine."""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES = (
    "hate",
    "violence",
    "sexual",
    "pii",
    "out_of_scope",
    "prompt_injection",
    "secret_leak",
)


@dataclass
class Identity:
    """Allow-list identifying the session's own customer (output leak check)."""

    email: str | None = None


@dataclass
class Decision:
    """Verdict of a guardrail on a message."""

    allowed: bool
    action: str  # "allow" | "block" | "mask"
    category: str | None = None
    reason: str = ""
    refusal: str | None = None
    sanitized: str | None = None  # masked text when action == "mask"
