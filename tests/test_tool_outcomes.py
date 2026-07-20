"""The Trace records what business tools returned, not just that they ran.

Escalation rate and tool-error rate are production metrics (chantier 005c); they
are read back from these steps rather than by instrumenting all ten tools.
"""

from __future__ import annotations

from conftest import build_reference_agent
from velmo.trace import Trace


def test_deterministic_escalation_is_recorded_as_a_tool_step() -> None:
    # O-2024-0103 is shipped: MODIFIABLE_STATUSES excludes it, so cancelling
    # escalates instead of failing silently.
    trace = Trace()
    answer = build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0103, je confirme", trace=trace
    )

    assert "conseiller" in answer
    tools = [s for s in trace.steps if s.stage == "tool"]
    assert [s.outcome for s in tools] == ["escalate"]
    assert tools[0].name == "cancel_order"


def test_deterministic_success_is_recorded_with_the_tool_action() -> None:
    # O-2024-0101 is paid, so cancelling actually goes through.
    trace = Trace()
    build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0101, je confirme", trace=trace
    )

    tools = [s for s in trace.steps if s.stage == "tool"]
    assert len(tools) == 1
    assert tools[0].outcome not in ("escalate", "error")


def test_unowned_order_is_recorded_as_a_tool_error() -> None:
    # O-2024-0110 belongs to C-sophie-martin: owned_order returns None and the
    # tool reports {"error": "not_found_or_forbidden"}.
    trace = Trace()
    build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0110, je confirme", trace=trace
    )

    tools = [s for s in trace.steps if s.stage == "tool"]
    assert [s.outcome for s in tools] == ["error"]


def test_a_read_only_turn_records_no_tool_outcome() -> None:
    # Only the modifying path reports a verdict; reads stay out of scope so the
    # escalation metric is not diluted by lookups.
    trace = Trace()
    build_reference_agent().respond(
        "C-marc-dubois", "Où en est ma commande O-2024-0101 ?", trace=trace
    )

    assert [s for s in trace.steps if s.stage == "tool"] == []


def test_running_without_a_trace_still_answers_the_same() -> None:
    message = "Je veux annuler ma commande O-2024-0103, je confirme"
    without = build_reference_agent().respond("C-marc-dubois", message)
    with_trace = build_reference_agent().respond("C-marc-dubois", message, trace=Trace())

    assert without == with_trace
