"""Fixture test file, so the repository looks like a tested project."""

from __future__ import annotations

from sample.calculator import Calculator, parse_operator


def test_add_rounds() -> None:
    assert Calculator(precision=2).add(1.111, 2.222) == 3.33


def test_parse_operator() -> None:
    assert parse_operator("+") == "add"
    assert parse_operator("nope") == "mul"
