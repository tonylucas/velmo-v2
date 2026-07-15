"""Unit tests for the demo trace recorder (velmo.trace)."""

from __future__ import annotations

from velmo.trace import Trace, TraceStep


def test_add_appends_a_step_in_order() -> None:
    trace = Trace()
    trace.add("guardrail_in", "detect_injection", "pass")
    trace.add("graph", "deterministic_node", "match")

    assert [(s.stage, s.name, s.outcome) for s in trace.steps] == [
        ("guardrail_in", "detect_injection", "pass"),
        ("graph", "deterministic_node", "match"),
    ]


def test_add_collects_keyword_detail() -> None:
    trace = Trace()
    trace.add("graph", "deterministic_node", "match", intent="order_status", order_id="O-2024-0101")

    assert trace.steps[0].detail == {"intent": "order_status", "order_id": "O-2024-0101"}


def test_step_defaults_are_empty() -> None:
    step = TraceStep(stage="graph", name="llm_node", outcome="done")

    assert step.detail == {}
    assert step.duration_ms == 0.0


def test_fresh_traces_do_not_share_state() -> None:
    # Guards against the classic mutable-default bug: a shared list would leak
    # one turn's steps into the next turn's trace.
    first = Trace()
    first.add("graph", "llm_node", "done")

    assert Trace().steps == []


def test_timed_records_the_measured_step() -> None:
    trace = Trace()
    with trace.timed("guardrail_in", "check_input") as step:
        step.outcome = "allow"

    assert trace.steps[0].outcome == "allow"
    assert trace.steps[0].duration_ms >= 0.0


def test_timed_records_the_step_even_when_the_body_raises() -> None:
    # A backend failure (Chroma down, Azure timeout) must still leave the step
    # in the trace: the demo panel is how one sees where the turn died.
    trace = Trace()
    try:
        with trace.timed("graph", "llm_node") as step:
            step.outcome = "started"
            raise RuntimeError("azure down")
    except RuntimeError:
        pass

    assert [(s.name, s.outcome) for s in trace.steps] == [("llm_node", "started")]


def test_path_reports_llm_when_the_llm_node_ran() -> None:
    trace = Trace()
    trace.add("graph", "deterministic_node", "no_match")
    trace.add("graph", "llm_node", "done")

    assert trace.path == "LLM"


def test_path_reports_deterministic_when_the_fast_path_matched() -> None:
    trace = Trace()
    trace.add("graph", "deterministic_node", "match", intent="order_status")

    assert trace.path == "déterministe"


def test_path_reports_blocked_when_an_input_guardrail_blocked() -> None:
    trace = Trace()
    trace.add("guardrail_in", "detect_injection", "match", category="prompt_injection")
    trace.add("guardrail_in", "check_input", "block", category="prompt_injection")

    assert trace.path == "bloqué"


def test_total_ms_sums_the_steps() -> None:
    trace = Trace()
    trace.add("guardrail_in", "check_input", "allow").duration_ms = 2.0
    trace.add("graph", "llm_node", "done").duration_ms = 1400.0

    assert trace.total_ms == 1402.0


def test_add_returns_the_step_it_recorded() -> None:
    trace = Trace()
    step = trace.add("graph", "llm_node", "done")

    assert step is trace.steps[0]


def test_a_detail_named_duration_ms_does_not_shadow_the_measured_duration() -> None:
    # `add` takes no duration parameter precisely so this cannot collide.
    trace = Trace()
    step = trace.add("tool", "get_order", "called", duration_ms="not a number")

    assert step.duration_ms == 0.0
    assert step.detail["duration_ms"] == "not a number"
