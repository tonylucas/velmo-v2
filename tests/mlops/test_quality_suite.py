from conftest import build_reference_agent

from velmo.mlops.suites.quality import run_quality_suite


def test_quality_suite_scores_reference_agent():
    note, latency_ms = run_quality_suite(build_reference_agent())
    assert note == 1.0  # measured offline: 8/8
    assert latency_ms >= 0.0
