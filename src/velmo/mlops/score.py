"""CLI entrypoint: run the evaluation, write the report, enforce the gate.

`python -m velmo.mlops.score --min-score 0.8` evaluates the offline agent by
default (the fast PR check, no secrets). `--prod` evaluates the real stack
(build_default_agent — Azure Content Safety included) for the tag -> prod
re-check. Exits non-zero when the gate blocks delivery.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from velmo.agent import Agent
from velmo.mlops import (
    DeliveryBlocked,
    Scores,
    current_version,
    enforce_threshold,
    run_eval,
    write_report,
)


def build_offline_agent() -> Agent:
    """Assemble a fully offline agent (seeded SQLite, LocalKB, LocalFactStore)."""
    from velmo.db import fresh_sqlite_session
    from velmo.guardrails import GuardrailEngine
    from velmo.kb_store import LocalKB
    from velmo.llm import OfflineChatModel
    from velmo.memory.fact_store import LocalFactStore
    from velmo.sampledata import seed

    session = fresh_sqlite_session()  # type: ignore[no-untyped-call]
    seed(session)
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=LocalKB(),
        store=LocalFactStore(),
    )


def _select_agent(prod: bool) -> Agent:
    if prod:
        from velmo.agent import build_default_agent

        return build_default_agent()
    return build_offline_agent()


def _summary(scores: Scores) -> str:
    return (
        f"version={current_version()} memory={scores.memory:.3f} "
        f"quality={scores.quality:.3f} block_rate={scores.block_rate:.3f} "
        f"fp_rate={scores.false_positive_rate:.3f} global={scores.global_:.3f} "
        f"latency_ms={scores.latency_ms:.1f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="velmo.mlops.score")
    parser.add_argument("--min-score", type=float, default=0.8)
    parser.add_argument("--prod", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("mlops/report.md"))
    args = parser.parse_args(argv)

    agent = _select_agent(args.prod)
    # `Evaluable.guardrails` is a plain Protocol attribute, so mypy treats it as
    # invariant against `Agent.guardrails: GuardrailEngine`, even though
    # GuardrailEngine structurally satisfies `_Guard`. See velmo.mlops._types.
    scores = run_eval(agent)  # type: ignore[arg-type]
    print(_summary(scores))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_report(scores, args.report)

    try:
        enforce_threshold(scores, args.min_score)
    except DeliveryBlocked as exc:
        print(f"DELIVERY BLOCKED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
