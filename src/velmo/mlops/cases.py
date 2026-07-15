"""Load the evaluation case sets from eval/*.jsonl."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# .../src/velmo/mlops/cases.py -> parents[3] is the repository root, where eval/ lives.
EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"


def load_jsonl(name: str) -> list[dict[str, Any]]:
    text = (EVAL_DIR / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def memory_cases() -> list[dict[str, Any]]:
    return load_jsonl("memory_cases.jsonl")


def guardrail_cases() -> list[dict[str, Any]]:
    return load_jsonl("guardrail_cases.jsonl")


def quality_cases() -> list[dict[str, Any]]:
    return load_jsonl("quality_cases.jsonl")
