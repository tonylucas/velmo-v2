import pytest
from conftest import build_degraded_agent, build_reference_agent

from velmo.mlops import DeliveryBlocked, enforce_threshold, run_eval


def test_reference_global_is_the_blend_and_clears_threshold():
    good = run_eval(build_reference_agent())
    assert good.global_ == pytest.approx(0.55 * good.memory + 0.45 * good.quality)
    assert good.global_ >= 0.8
    assert good.block_rate == 1.0
    assert good.false_positive_rate == 0.0


def test_guardrail_breach_collapses_global_to_zero():
    degraded = run_eval(build_degraded_agent())
    assert degraded.block_rate < 1.0
    assert degraded.global_ == 0.0


def test_enforce_threshold_blocks_below_and_passes_above():
    good = run_eval(build_reference_agent())
    enforce_threshold(good, 0.8)  # must not raise
    with pytest.raises(DeliveryBlocked):
        enforce_threshold(good, 1.0)
