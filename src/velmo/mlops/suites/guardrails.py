"""Guardrail evaluation suite.

Calls the guardrail engine directly (not respond), honouring each case's `where`
side. Produces the two hard-gate metrics: block rate over the malicious cases,
false-positive rate over the legitimate ones.
"""

from __future__ import annotations

from typing import Any

from velmo.guardrails import Decision
from velmo.mlops._types import Evaluable
from velmo.mlops.cases import guardrail_cases


def _decide(agent: Evaluable, case: dict[str, Any]) -> Decision:
    if case["where"] == "output":
        return agent.guardrails.check_output(case["message"])
    return agent.guardrails.check_input(case["message"])


def run_guardrail_suite(agent: Evaluable) -> tuple[float, float]:
    cases = guardrail_cases()
    malicious = [c for c in cases if c["expected_action"] == "block"]
    legit = [c for c in cases if c["expected_action"] == "allow"]

    blocked = sum(_decide(agent, c).action == "block" for c in malicious)
    false_positives = sum(_decide(agent, c).action == "block" for c in legit)

    block_rate = blocked / len(malicious)
    false_positive_rate = false_positives / len(legit)
    return block_rate, false_positive_rate
