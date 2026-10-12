"""Line counting.

Comment detection is a documented heuristic: line-comment prefixes plus
C-style block comments. It intentionally ignores string literals, because the
metric only needs to rank languages, not be exact.
"""

from __future__ import annotations

from dataclasses import dataclass

from .languages import language_of


@dataclass(frozen=True, slots=True)
class Loc:
    lines: int = 0
    non_blank: int = 0
    comment: int = 0
    code: int = 0
    max_line_length: int = 0


EMPTY = Loc()


def split_lines(text: str) -> list[str]:
    """Split the way an editor counts lines: no phantom trailing line."""
    normalized = text[1:] if text.startswith("\ufeff") else text
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == "":
        return []
    lines = normalized.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def count_lines(rel: str, text: str) -> Loc:
    lines = split_lines(text)
    language = language_of(rel)
    prefix = language.line_comment if language is not None else ""

    non_blank = 0
    comment = 0
    max_len = 0
    in_block = False

    for line in lines:
        if len(line) > max_len:
            max_len = len(line)

        stripped = line.strip()
        if stripped == "":
            continue
        non_blank += 1

        if in_block:
            comment += 1
            if "*/" in stripped:
                in_block = False
            continue

        if prefix and stripped.startswith(prefix):
            comment += 1
            continue

        if stripped.startswith("/*"):
            comment += 1
            if "*/" not in stripped:
                in_block = True
            continue

    return Loc(
        lines=len(lines),
        non_blank=non_blank,
        comment=comment,
        code=max(0, non_blank - comment),
        max_line_length=max_len,
    )


def add(left: Loc, right: Loc) -> Loc:
    return Loc(
        lines=left.lines + right.lines,
        non_blank=left.non_blank + right.non_blank,
        comment=left.comment + right.comment,
        code=left.code + right.code,
        max_line_length=max(left.max_line_length, right.max_line_length),
    )
