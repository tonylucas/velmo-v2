"""GuardrailEngine: orchestrates deterministic detectors (offline) with optional
Azure Content Safety reinforcement (prod), and journals every block/mask."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .content_safety import get_moderator
from .decision import Decision, Identity
from .detectors import (
    detect_injection,
    detect_moderation,
    detect_out_of_scope,
    detect_secret_leak,
    foreign_email,
    scan_secrets,
)
from .refusals import refusal_for


@dataclass
class GuardrailEngine:
    """Applies input/output guardrails and records decisions in `events`."""

    events: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        # None offline; a Content Safety client when the endpoint is configured.
        self._moderator = get_moderator()

    def _log(self, category: str, where: str, action: str, reason: str) -> None:
        self.events.append(
            {
                "category": category,
                "where": where,
                "action": action,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def _block(self, category: str, where: str) -> Decision:
        self._log(category, where, "block", f"{category} detected")
        return Decision(
            allowed=False,
            action="block",
            category=category,
            reason=f"{category} detected",
            refusal=refusal_for(category),
        )

    def check_input(self, message: str) -> Decision:
        for detector in (
            detect_injection,
            detect_moderation,
            detect_out_of_scope,
            detect_secret_leak,
        ):
            category = detector(message)
            if category:
                return self._block(category, "input")

        if self._moderator is not None:  # prod reinforcement, never hit offline
            if self._moderator.shield(message):
                return self._block("prompt_injection", "input")
            blocked = self._moderator.analyze(message)
            if blocked:
                return self._block(sorted(blocked)[0], "input")

        masked, found = scan_secrets(message)
        if found:
            self._log("pii", "input", "mask", "masked sensitive data")
            return Decision(
                allowed=True,
                action="mask",
                category="pii",
                reason="masked sensitive data",
                sanitized=masked,
            )

        return Decision(allowed=True, action="allow")

    def check_output(self, text: str, *, identity: Identity | None = None) -> Decision:
        category = detect_secret_leak(text)
        if category:
            return self._block(category, "output")

        _, found = scan_secrets(text)
        if found:
            return self._block("pii", "output")

        if identity is not None and foreign_email(text, identity):
            return self._block("pii", "output")

        moderation = detect_moderation(text)
        if moderation:
            return self._block(moderation, "output")

        if self._moderator is not None:  # prod reinforcement, never hit offline
            blocked = self._moderator.analyze(text)
            if blocked:
                return self._block(sorted(blocked)[0], "output")

        return Decision(allowed=True, action="allow")
