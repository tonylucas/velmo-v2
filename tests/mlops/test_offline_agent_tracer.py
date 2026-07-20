"""The offline eval gate must not export to Langfuse, by construction."""

from __future__ import annotations

from velmo.mlops.score import build_offline_agent
from velmo.observability import NoOpTracer


def test_build_offline_agent_uses_noop_tracer_regardless_of_environment(monkeypatch) -> None:
    # Structural, not environmental: on any host that exports LANGFUSE_* (the
    # Container App itself, or a developer shell with the keys loaded),
    # Agent's default `tracer or get_tracer()` would build a real
    # LangfuseTracer and open a span per eval turn — inflating the reported
    # latency_ms with real network round-trips, and pushing eval fixtures into
    # the production Langfuse project under `--prod`. build_offline_agent must
    # pass tracer=NoOpTracer() explicitly so the gate's determinism does not
    # depend on the environment being clean.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    agent = build_offline_agent()

    assert isinstance(agent.tracer, NoOpTracer)
    assert agent.tracer.records is False
