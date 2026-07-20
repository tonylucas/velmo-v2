"""Renders a TurnLog to markdown for the demo panel.

Pure presentation: takes a TurnLog, returns strings. Imports no Streamlit, so it
stays unit-testable in CI (which installs no `demo` extra) and keeps
``demo_app`` a thin Streamlit layer over it.
"""

from __future__ import annotations

from .turn_log import TurnLog, TurnLogStep

_STAGE_LABELS = {
    "guardrail_in": (":material/shield:", "Garde-fou entrée"),
    "memory": (":material/psychology:", "Mémoire long terme"),
    "graph": (":material/account_tree:", "Graphe"),
    "tool": (":material/build:", "Outils métier"),
    "guardrail_out": (":material/shield_lock:", "Garde-fou sortie"),
}

# Verdict -> badge colour. Green passes, red blocks, orange masks, grey is inert.
_OUTCOME_COLOURS = {
    "allow": "green",
    "pass": "gray",
    "skip": "gray",
    "nothing": "gray",
    "empty": "gray",
    "no_match": "gray",
    "block": "red",
    "match": "orange",
    "mask": "orange",
    "called": "blue",
    "injected": "blue",
    "written": "blue",
    "done": "green",
    "pending": "gray",
}


def stage_label(stage: str) -> str:
    """Human label for a pipeline stage, icon included."""
    icon, label = _STAGE_LABELS.get(stage, (":material/help:", stage))
    return f"{icon} {label}"


def outcome_badge(outcome: str) -> str:
    """Markdown badge for a step verdict.

    An unknown outcome falls back to a grey badge rather than disappearing: the
    panel must never silently drop a step it does not recognise.
    """
    colour = _OUTCOME_COLOURS.get(outcome, "gray")
    return f":{colour}-badge[{outcome}]"


def format_detail(step: TurnLogStep) -> str:
    """One-line `clé : valeur` summary of a step's detail; empty when it has none."""
    return " · ".join(f"{key} : {value}" for key, value in step.detail.items())


def turn_title(index: int, turn_log: TurnLog, clock: str) -> str:
    """Expander title summarising a turn: index, time, route and duration."""
    return f"Tour {index} · {clock} · {turn_log.path} · {turn_log.total_ms:.0f} ms"


def grouped_steps(turn_log: TurnLog) -> list[tuple[str, list[TurnLogStep]]]:
    """Steps grouped into consecutive runs of the same stage.

    Grouping is positional rather than by a fixed stage order, so a stage that
    recurs (tools called around the LLM node) still reads chronologically.
    """
    groups: list[tuple[str, list[TurnLogStep]]] = []
    for step in turn_log.steps:
        if groups and groups[-1][0] == step.stage:
            groups[-1][1].append(step)
        else:
            groups.append((step.stage, [step]))
    return groups
