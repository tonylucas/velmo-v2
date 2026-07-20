"""CLI entrypoint: run the evaluation, write the report, enforce the gate.

`python -m velmo.mlops.score --min-score 0.90` evaluates the offline agent by
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
    """Assemble a fully offline agent (seeded SQLite, LocalKB, LocalFactStore).

    Passes `tracer=NoOpTracer()` explicitly rather than letting `Agent` default
    to `get_tracer()`. `get_tracer()` reads `LANGFUSE_*` from the environment,
    so on any host that exports those (the Container App itself, or a dev shell
    with the keys loaded) the "offline" gate would silently start exporting —
    a span per eval turn flushed over the network, inflating the reported
    `latency_ms` with real HTTP round-trips. The offline gate's determinism
    must hold by construction, not by hoping the environment is clean.
    """
    from velmo.db import fresh_sqlite_session
    from velmo.guardrails import GuardrailEngine
    from velmo.kb_store import LocalKB
    from velmo.llm import OfflineChatModel
    from velmo.memory.fact_store import LocalFactStore
    from velmo.observability import NoOpTracer
    from velmo.sampledata import seed

    session = fresh_sqlite_session()
    seed(session)
    return Agent(
        chat_model=OfflineChatModel(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=LocalKB(),
        store=LocalFactStore(),
        tracer=NoOpTracer(),
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
    parser.add_argument("--min-score", type=float, default=0.90)
    parser.add_argument("--prod", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("mlops/report.md"))
    args = parser.parse_args(argv)

    agent = _select_agent(args.prod)
    scores = run_eval(agent)
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
