"""Neutralise string literal contents before text-level scanning.

A marker or a credential-looking word inside a string literal is not debt: it is
either test data or prose. ``test_todos.py`` is the proof — its assertions
contain ``"# FIXME(alice): overflow here"``, which a naive line scanner reports
as a real marker in the project that defines the scanner.

For Python this is exact: the ``ast`` module gives the byte span of every string
constant, and those spans are blanked out. Other languages keep the previous
behaviour, and the limitation is documented rather than hidden.

Two details are easy to get wrong and are handled explicitly:

* ``ast`` column offsets count **UTF-8 bytes**, not characters, so the spans are
  translated to character indices before anything is edited;
* the translation must happen against the **original** text for every span,
  because blanking a multi-byte literal changes the byte length of the line and
  invalidates the offsets of any span after it.

Line count and line numbering are always preserved, so reported line numbers
still match the file on disk.
"""

from __future__ import annotations

import ast

PYTHON = "Python"


def _terminator_of(line: str) -> tuple[str, str]:
    for candidate in ("\r\n", "\n", "\r"):
        if line.endswith(candidate):
            return line[: -len(candidate)], candidate
    return line, ""


def _string_spans(text: str) -> list[tuple[int, int, int, int]]:
    """Byte spans of every string constant, or ``[]`` when the file does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return []

    spans: list[tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        end_line = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if not isinstance(end_line, int) or not isinstance(end_col, int):
            continue
        spans.append((node.lineno, node.col_offset, end_line, end_col))
    return spans


def _to_character_ranges(
    bodies: list[str], spans: list[tuple[int, int, int, int]]
) -> dict[int, list[tuple[int, int]]]:
    """Translate byte spans to character ranges, using the untouched lines."""
    ranges: dict[int, list[tuple[int, int]]] = {}

    for start_line, start_col, end_line, end_col in spans:
        for number in range(start_line, end_line + 1):
            index = number - 1
            if index < 0 or index >= len(bodies):
                continue

            encoded = bodies[index].encode("utf-8")
            begin = start_col if number == start_line else 0
            finish = end_col if number == end_line else len(encoded)
            if begin >= len(encoded):
                continue
            finish = min(finish, len(encoded))

            char_begin = len(encoded[:begin].decode("utf-8", errors="replace"))
            char_end = len(encoded[:finish].decode("utf-8", errors="replace"))
            if char_end > char_begin:
                ranges.setdefault(index, []).append((char_begin, char_end))

    return ranges


def mask_string_literals(text: str, language: str) -> str:
    """Return ``text`` with Python string literal contents replaced by spaces.

    Other languages are returned unchanged. A file that does not parse is also
    returned unchanged, so a half-written module still gets a regex-level scan.
    """
    if language != PYTHON:
        return text

    spans = _string_spans(text)
    if not spans:
        return text

    raw_lines = text.splitlines(keepends=True)
    if not raw_lines:
        return text

    bodies: list[str] = []
    terminators: list[str] = []
    for raw in raw_lines:
        body, terminator = _terminator_of(raw)
        bodies.append(body)
        terminators.append(terminator)

    ranges = _to_character_ranges(bodies, spans)

    for index, line_ranges in ranges.items():
        characters = list(bodies[index])
        # Right to left, so an earlier range is still addressable.
        for char_begin, char_end in sorted(line_ranges, reverse=True):
            characters[char_begin:char_end] = " " * (char_end - char_begin)
        bodies[index] = "".join(characters)

    return "".join(body + terminator for body, terminator in zip(bodies, terminators, strict=True))
