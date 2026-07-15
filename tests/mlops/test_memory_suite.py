"""Test the memory evaluation suite."""

from conftest import build_reference_agent

from velmo.mlops.suites.memory import run_memory_suite


def test_memory_suite_scores_reference_agent():
    note, sub_scores = run_memory_suite(build_reference_agent())
    assert 0.0 <= note <= 1.0
    assert note >= 0.8  # measured offline: 11/12 = 0.917
    assert set(sub_scores) >= {"R1", "R2", "R3", "R5"}
    assert all(0.0 <= v <= 1.0 for v in sub_scores.values())
