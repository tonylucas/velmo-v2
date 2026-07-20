"""Unit tests for the TurnLog recorder (velmo.turn_log)."""

from __future__ import annotations

from velmo.turn_log import TurnLog, TurnLogStep


def test_add_appends_a_step_in_order() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "detect_injection", "pass")
    turn_log.add("graph", "deterministic_node", "match")

    assert [(s.stage, s.name, s.outcome) for s in turn_log.steps] == [
        ("guardrail_in", "detect_injection", "pass"),
        ("graph", "deterministic_node", "match"),
    ]


def test_add_collects_keyword_detail() -> None:
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "match", intent="order_status", order_id="O-2024-0101")

    assert turn_log.steps[0].detail == {"intent": "order_status", "order_id": "O-2024-0101"}


def test_step_defaults_are_empty() -> None:
    step = TurnLogStep(stage="graph", name="llm_node", outcome="done")

    assert step.detail == {}
    assert step.duration_ms == 0.0


def test_fresh_turn_logs_do_not_share_state() -> None:
    # Guards against the classic mutable-default bug: a shared list would leak
    # one turn's steps into the next turn's turn_log.
    first = TurnLog()
    first.add("graph", "llm_node", "done")

    assert TurnLog().steps == []


def test_timed_records_the_measured_step() -> None:
    turn_log = TurnLog()
    with turn_log.timed("guardrail_in", "check_input") as step:
        step.outcome = "allow"

    assert turn_log.steps[0].outcome == "allow"
    assert turn_log.steps[0].duration_ms >= 0.0


def test_timed_records_the_step_even_when_the_body_raises() -> None:
    # A backend failure (Chroma down, Azure timeout) must still leave the step
    # in the turn_log: the demo panel is how one sees where the turn died.
    turn_log = TurnLog()
    try:
        with turn_log.timed("graph", "llm_node") as step:
            step.outcome = "started"
            raise RuntimeError("azure down")
    except RuntimeError:
        pass

    assert [(s.name, s.outcome) for s in turn_log.steps] == [("llm_node", "started")]


def test_path_reports_llm_when_the_llm_node_ran() -> None:
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "no_match")
    turn_log.add("graph", "llm_node", "done")

    assert turn_log.path == "LLM"


def test_path_reports_deterministic_when_the_fast_path_matched() -> None:
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "match", intent="order_status")

    assert turn_log.path == "déterministe"


def test_path_reports_blocked_when_an_input_guardrail_blocked() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "detect_injection", "match", category="prompt_injection")
    turn_log.add("guardrail_in", "check_input", "block", category="prompt_injection")

    assert turn_log.path == "bloqué"


def test_total_ms_sums_the_steps() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "check_input", "allow").duration_ms = 2.0
    turn_log.add("graph", "llm_node", "done").duration_ms = 1400.0

    assert turn_log.total_ms == 1402.0


def test_add_returns_the_step_it_recorded() -> None:
    turn_log = TurnLog()
    step = turn_log.add("graph", "llm_node", "done")

    assert step is turn_log.steps[0]


def test_a_detail_named_duration_ms_does_not_shadow_the_measured_duration() -> None:
    # `add` takes no duration parameter precisely so this cannot collide.
    turn_log = TurnLog()
    step = turn_log.add("tool", "get_order", "called", duration_ms="not a number")

    assert step.duration_ms == 0.0
    assert step.detail["duration_ms"] == "not a number"
