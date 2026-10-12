"""Presentation helpers."""

from __future__ import annotations

import pytest

from codebase_insight.core import text


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (10 * 1024, "10.0 KB"),
        (150 * 1024, "150 KB"),
        (5 * 1024 * 1024, "5.0 MB"),
        (3 * 1024**3, "3.0 GB"),
        (2 * 1024**4, "2.0 TB"),
    ],
)
def test_human_bytes(size: int, expected: str) -> None:
    assert text.human_bytes(size) == expected


def test_human_bytes_caps_at_terabytes() -> None:
    assert text.human_bytes(5 * 1024**5).endswith("TB")


def test_percent_handles_a_zero_denominator() -> None:
    assert text.percent(1, 0) == "-"
    assert text.percent(1, 4) == "25.0%"
    assert text.percent(1, 3, digits=0) == "33%"


def test_truncate_collapses_whitespace_and_marks_the_cut() -> None:
    assert text.truncate("a   b\n c", 20) == "a b c"
    assert text.truncate("abcdefghij", 5) == "abcd…"
    assert text.truncate("abc", 0) == "…"


def test_plural() -> None:
    assert text.plural(1, "file") == "file"
    assert text.plural(0, "file") == "files"
    assert text.plural(2, "match", "matches") == "matches"
