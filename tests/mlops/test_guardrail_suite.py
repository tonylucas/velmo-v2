from conftest import build_degraded_agent, build_reference_agent

from velmo.mlops.suites.guardrails import run_guardrail_suite


def test_reference_blocks_all_and_no_false_positive():
    block_rate, false_positive_rate = run_guardrail_suite(build_reference_agent())
    assert block_rate == 1.0
    assert false_positive_rate == 0.0


def test_degraded_agent_blocks_nothing():
    block_rate, _fp = run_guardrail_suite(build_degraded_agent())
    assert block_rate == 0.0
