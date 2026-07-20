"""Pure presentation helpers of the demo TurnLog panel.

`velmo.turn_log_view` renders a TurnLog to markdown strings and imports no Streamlit,
so these run in CI (which installs no `demo` extra) rather than being skipped.
"""

from __future__ import annotations

from velmo.turn_log import TurnLog
from velmo.turn_log_view import format_detail, grouped_steps, outcome_badge, stage_label, turn_title


def test_stage_label_names_every_pipeline_stage_in_french() -> None:
    from velmo.turn_log import STAGES

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
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "match", intent="order_status").duration_ms = 120.0

    title = turn_title(3, turn_log, "14:22:07")

    assert "3" in title
    assert "14:22:07" in title
    assert "déterministe" in title
    assert "120" in title


def test_turn_title_reports_a_blocked_turn() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "detect_injection", "match", category="prompt_injection")
    turn_log.add("guardrail_in", "check_input", "block", category="prompt_injection")

    assert "bloqué" in turn_title(1, turn_log, "14:21:44")


def test_format_detail_renders_the_key_values() -> None:
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "match", intent="order_status")

    assert "intent" in format_detail(turn_log.steps[0])
    assert "order_status" in format_detail(turn_log.steps[0])


def test_format_detail_is_empty_when_there_is_no_detail() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "detect_injection", "pass")

    assert format_detail(turn_log.steps[0]) == ""


def test_grouped_steps_groups_consecutive_stages() -> None:
    turn_log = TurnLog()
    turn_log.add("guardrail_in", "detect_injection", "pass")
    turn_log.add("guardrail_in", "check_input", "allow")
    turn_log.add("graph", "llm_node", "done")

    assert [(stage, len(steps)) for stage, steps in grouped_steps(turn_log)] == [
        ("guardrail_in", 2),
        ("graph", 1),
    ]


def test_grouped_steps_keeps_a_recurring_stage_in_chronological_order() -> None:
    # Tools are called around the LLM node; grouping by a fixed stage order would
    # reorder them and misrepresent what happened.
    turn_log = TurnLog()
    turn_log.add("graph", "deterministic_node", "no_match")
    turn_log.add("tool", "get_order", "called")
    turn_log.add("graph", "llm_node", "done")

    assert [stage for stage, _ in grouped_steps(turn_log)] == ["graph", "tool", "graph"]
