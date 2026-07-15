"""Render the versioned evaluation report.

Column labels are deliberately accent-free (`memoire`, `cout`, …): the frozen
test lower-cases the file and greps for those ASCII tokens, so accented labels
would not match. The title keeps its accent (French correctness).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .version import current_version

if TYPE_CHECKING:
    from . import Scores

_HEADER = (
    "# Rapport d'évaluation Velmo\n\n"
    "| version | note memoire | taux de blocage | taux de faux positifs "
    "| note qualite | note globale | latence (ms) | cout |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def write_report(scores: Scores, path: Path) -> None:
    """Append a versioned row to the Markdown report, creating it with a header if new."""
    row = (
        f"| {current_version()} | {scores.memory:.3f} | {scores.block_rate:.3f} "
        f"| {scores.false_positive_rate:.3f} | {scores.quality:.3f} "
        f"| {scores.global_:.3f} | {scores.latency_ms:.1f} | {scores.cost:.4f} |\n"
    )
    path = Path(path)
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + row, encoding="utf-8")
    else:
        path.write_text(_HEADER + row, encoding="utf-8")
