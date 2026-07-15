"""Pure presentation helpers of the demo trace panel.

`velmo.trace_view` renders a Trace to markdown strings and imports no Streamlit,
so these run in CI (which installs no `demo` extra) rather than being skipped.
"""

from __future__ import annotations

from velmo.trace import Trace
from velmo.trace_view import format_detail, grouped_steps, outcome_badge, stage_label, turn_title


def test_stage_label_names_every_pipeline_stage_in_french() -> None:
    from velmo.trace import STAGES

    for stage in STAGES:
        assert stage_label(stage) != stage, f"stage {stage} has no French label"


def test_outcome_badge_colours_a_block_in_red() -> None:
    assert "red-badge" in outcome_badge("block")


def test_outcome_badge_colours_an_allow_in_green() -> None:
    assert "green-badge" in outcome_badge("allow")


def test_outcome_badge_colours_a_mask_in_orange() -> None:
    assert "orange-badge" in outcome_badge("mask")


def test_outcome_badge_keeps_an_unknown_outcome_visible() -> None:
    # A new outcome must still render rather than vanish from the panel.
    assert "surprise" in outcome_badge("surprise")


def test_turn_title_shows_index_path_and_duration() -> None:
    trace = Trace()
    trace.add("graph", "deterministic_node", "match", intent="order_status").duration_ms = 120.0

    title = turn_title(3, trace, "14:22:07")

    assert "3" in title
    assert "14:22:07" in title
    assert "déterministe" in title
    assert "120" in title


def test_turn_title_reports_a_blocked_turn() -> None:
    trace = Trace()
    trace.add("guardrail_in", "detect_injection", "match", category="prompt_injection")
    trace.add("guardrail_in", "check_input", "block", category="prompt_injection")

    assert "bloqué" in turn_title(1, trace, "14:21:44")


def test_format_detail_renders_the_key_values() -> None:
    trace = Trace()
    trace.add("graph", "deterministic_node", "match", intent="order_status")

    assert "intent" in format_detail(trace.steps[0])
    assert "order_status" in format_detail(trace.steps[0])


def test_format_detail_is_empty_when_there_is_no_detail() -> None:
    trace = Trace()
    trace.add("guardrail_in", "detect_injection", "pass")

    assert format_detail(trace.steps[0]) == ""


def test_grouped_steps_groups_consecutive_stages() -> None:
    trace = Trace()
    trace.add("guardrail_in", "detect_injection", "pass")
    trace.add("guardrail_in", "check_input", "allow")
    trace.add("graph", "llm_node", "done")

    assert [(stage, len(steps)) for stage, steps in grouped_steps(trace)] == [
        ("guardrail_in", 2),
        ("graph", 1),
    ]


def test_grouped_steps_keeps_a_recurring_stage_in_chronological_order() -> None:
    # Tools are called around the LLM node; grouping by a fixed stage order would
    # reorder them and misrepresent what happened.
    trace = Trace()
    trace.add("graph", "deterministic_node", "no_match")
    trace.add("tool", "get_order", "called")
    trace.add("graph", "llm_node", "done")

    assert [stage for stage, _ in grouped_steps(trace)] == ["graph", "tool", "graph"]
