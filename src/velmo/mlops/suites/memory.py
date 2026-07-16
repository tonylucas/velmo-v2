"""Memory evaluation suite.

Replays each case's user turns and scores on RETAINED STATE (short-term messages
plus durable facts), never on the offline model's echo — mirroring
tests/acceptance/test_memory.py. Each case runs on its own isolated user id so a
repeated id in the data set cannot cross-contaminate.
"""

from __future__ import annotations

from collections import defaultdict

from velmo.mlops._types import Evaluable
from velmo.mlops.cases import memory_cases


def _retained_state(agent: Evaluable, uid: str) -> str:
    messages = [str(m.content) for m in agent.get_state(uid)]
    facts = [f.content for f in agent.inspect_memory(uid)]
    return "\n".join(messages + facts)


def _durable_facts(agent: Evaluable, uid: str) -> str:
    return "\n".join(f.content for f in agent.inspect_memory(uid))


def run_memory_suite(agent: Evaluable) -> tuple[float, dict[str, float]]:
    cases = memory_cases()
    tag_passed: dict[str, int] = defaultdict(int)
    tag_total: dict[str, int] = defaultdict(int)
    passed = 0
    for case in cases:
        uid = f"{case['id']}::{case['user_id']}"
        user_turns = [turn["content"] for turn in case["turns"] if turn["role"] == "user"]
        for content in user_turns:
            agent.respond(uid, content)

        ev = case["evaluation"]
        if "expected_substring" in ev:
            ok = ev["expected_substring"] in _retained_state(agent, uid)
        else:
            # Complete the forget flow: the vrai agent only asks for confirmation
            # on the first request (FR-010), so confirm before checking deletion.
            agent.respond(uid, f"{user_turns[-1]} je confirme")
            ok = ev["forbidden_substring"] not in _durable_facts(agent, uid)

        passed += int(ok)
        tag = case.get("tag", "?")
        tag_total[tag] += 1
        tag_passed[tag] += int(ok)

    note = passed / len(cases)
    sub_scores = {tag: tag_passed[tag] / tag_total[tag] for tag in tag_total}
    return note, sub_scores
