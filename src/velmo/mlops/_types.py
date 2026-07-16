"""Structural protocol for anything the evaluation suites can drive.

Kept in its own module so the suites and the package __init__ can both import it
without a circular dependency. Satisfied by velmo.agent.Agent and by the test
doubles in tests/conftest.py.
"""

from __future__ import annotations

from typing import Any, Protocol

from velmo.guardrails import Decision


class _Guard(Protocol):
    def check_input(self, message: str) -> Decision: ...

    def check_output(self, text: str, *, identity: Any = None) -> Decision: ...


class Evaluable(Protocol):
    @property
    def guardrails(self) -> _Guard: ...

    def respond(self, user_id: str, message: str) -> str: ...

    def get_state(self, user_id: str) -> list[Any]: ...

    def inspect_memory(self, user_id: str) -> list[Any]: ...
