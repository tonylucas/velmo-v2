"""GuardrailEngine: orchestrates deterministic detectors (offline) with optional
Azure Content Safety reinforcement (prod), and journals every block/mask."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..trace import Trace
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

INPUT_DETECTORS = (
    detect_injection,
    detect_moderation,
    detect_out_of_scope,
    detect_secret_leak,
)


@dataclass
class GuardrailEngine:
    """Applies input/output guardrails and records decisions in `events`.

    Every check takes an optional `trace` (the demo panel). Tracing observes and
    never alters a verdict; `events` stays the compliance journal, unaffected.
    """

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

    def _block(self, category: str, where: str, trace: Trace | None = None) -> Decision:
        self._log(category, where, "block", f"{category} detected")
        if trace is not None:
            stage = "guardrail_in" if where == "input" else "guardrail_out"
            trace.add(stage, f"check_{where}", "block", category=category)
        return Decision(
            allowed=False,
            action="block",
            category=category,
            reason=f"{category} detected",
            refusal=refusal_for(category),
        )

    def check_input(self, message: str, *, trace: Trace | None = None) -> Decision:
        for detector in INPUT_DETECTORS:
            category = detector(message)
            if trace is not None:
                # A detector that never runs is absent from the trace, so the
                # short-circuit at the first match stays visible in the panel.
                trace.add(
                    "guardrail_in",
                    detector.__name__,
                    "match" if category else "pass",
                    **({"category": category} if category else {}),
                )
            if category:
                return self._block(category, "input", trace)

        if self._moderator is not None:  # prod reinforcement, never hit offline
            if self._moderator.shield(message):
                if trace is not None:
                    trace.add(
                        "guardrail_in",
                        "content_safety.shield",
                        "match",
                        category="prompt_injection",
                    )
                return self._block("prompt_injection", "input", trace)
            if trace is not None:
                trace.add("guardrail_in", "content_safety.shield", "pass")
            blocked = self._moderator.analyze(message)
            if trace is not None:
                trace.add(
                    "guardrail_in",
                    "content_safety.analyze",
                    "match" if blocked else "pass",
                    **({"categories": sorted(blocked)} if blocked else {}),
                )
            if blocked:
                return self._block(sorted(blocked)[0], "input", trace)

        masked, found = scan_secrets(message)
        if trace is not None:
            trace.add(
                "guardrail_in",
                "scan_secrets",
                "match" if found else "pass",
                **({"category": "pii", "sanitized": masked} if found else {}),
            )
        if found:
            self._log("pii", "input", "mask", "masked sensitive data")
            if trace is not None:
                trace.add("guardrail_in", "check_input", "mask", category="pii")
            return Decision(
                allowed=True,
                action="mask",
                category="pii",
                reason="masked sensitive data",
                sanitized=masked,
            )

        if trace is not None:
            trace.add("guardrail_in", "check_input", "allow")
        return Decision(allowed=True, action="allow")

    def check_output(
        self,
        text: str,
        *,
        identity: Identity | None = None,
        trace: Trace | None = None,
    ) -> Decision:
        category = detect_secret_leak(text)
        if trace is not None:
            trace.add(
                "guardrail_out",
                "detect_secret_leak",
                "match" if category else "pass",
                **({"category": category} if category else {}),
            )
        if category:
            return self._block(category, "output", trace)

        _, found = scan_secrets(text)
        if trace is not None:
            trace.add(
                "guardrail_out",
                "scan_secrets",
                "match" if found else "pass",
                **({"category": "pii"} if found else {}),
            )
        if found:
            return self._block("pii", "output", trace)

        leaked = foreign_email(text, identity) if identity is not None else None
        if trace is not None:
            if identity is None:
                trace.add("guardrail_out", "foreign_email", "skip", reason="identité inconnue")
            else:
                trace.add(
                    "guardrail_out",
                    "foreign_email",
                    "match" if leaked else "pass",
                    **({"category": "pii", "email": leaked} if leaked else {}),
                )
        if leaked:
            return self._block("pii", "output", trace)

        moderation = detect_moderation(text)
        if trace is not None:
            trace.add(
                "guardrail_out",
                "detect_moderation",
                "match" if moderation else "pass",
                **({"category": moderation} if moderation else {}),
            )
        if moderation:
            return self._block(moderation, "output", trace)

        if self._moderator is not None:  # prod reinforcement, never hit offline
            blocked = self._moderator.analyze(text)
            if trace is not None:
                trace.add(
                    "guardrail_out",
                    "content_safety.analyze",
                    "match" if blocked else "pass",
                    **({"categories": sorted(blocked)} if blocked else {}),
                )
            if blocked:
                return self._block(sorted(blocked)[0], "output", trace)

        if trace is not None:
            trace.add("guardrail_out", "check_output", "allow")
        return Decision(allowed=True, action="allow")
