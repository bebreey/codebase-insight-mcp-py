"""Module under test for the codebase-insight fixture repository.

The declarations and debt markers here are asserted by the analyser tests.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PRECISION = 6
MAX_OPERANDS = 32


@dataclass(frozen=True)
class Calculation:
    """A single arithmetic result."""

    operator: str
    result: float


class Calculator:
    """Small arithmetic helper with a pluggable rounding policy."""

    def __init__(self, precision: int = DEFAULT_PRECISION) -> None:
        self.precision = precision

    # TODO(alice): support unary minus in the parser
    def add(self, left: float, right: float) -> float:
        """Add two numbers and round the result."""
        return self._round(left + right)

    def _round(self, value: float) -> float:
        # HACK: relies on the platform rounding mode
        return round(value, self.precision)

    @staticmethod
    def describe() -> str:
        def decorate(text: str) -> str:
            return f"[{text}]"

        # FIXME: the description is not localised yet
        return decorate("calculator")


def parse_operator(raw: str) -> str:
    """Map a symbol or a word onto an operator name."""
    if raw in {"+", "add"}:
        return "add"
    if raw in {"-", "sub"}:
        return "sub"
    return "mul"


__all__ = ["Calculation", "Calculator", "DEFAULT_PRECISION", "MAX_OPERANDS", "parse_operator"]
