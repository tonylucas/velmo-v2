"""Quality evaluation suite.

One deterministic single-turn question per case; success iff the expected
substring appears in the answer. Also returns the mean per-turn latency — a
comparative signal between versions, not an SLA (percentiles live in prod
monitoring, chantier 005c).
"""

from __future__ import annotations

import time

from velmo.mlops._types import Evaluable
from velmo.mlops.cases import quality_cases


def run_quality_suite(agent: Evaluable) -> tuple[float, float]:
    cases = quality_cases()
    passed = 0
    durations_ms: list[float] = []
    for case in cases:
        start = time.perf_counter()
        answer = agent.respond(case["user_id"], case["question"])
        durations_ms.append((time.perf_counter() - start) * 1000.0)
        if case["expected_substring"] in answer:
            passed += 1
    note = passed / len(cases)
    latency_ms = sum(durations_ms) / len(durations_ms)
    return note, latency_ms
