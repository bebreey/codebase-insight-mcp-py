"""Tech-debt marker scanning (TODO / FIXME / HACK / ...).

A marker only counts when it sits in a comment or on a bare line, and the text
that follows carries actual prose. Without both conditions a table of tag names
in the source — like the one in this very module — reports itself as debt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import truncate

TODO = "TODO"
FIXME = "FIXME"
HACK = "HACK"
XXX = "XXX"
BUG = "BUG"
OPTIMIZE = "OPTIMIZE"
DEPRECATED = "DEPRECATED"
REVIEW = "REVIEW"
NOTE = "NOTE"

ALL_TAGS: tuple[str, ...] = (TODO, FIXME, HACK, XXX, BUG, OPTIMIZE, DEPRECATED, REVIEW, NOTE)
DEFAULT_TAGS: tuple[str, ...] = (TODO, FIXME, HACK, XXX, BUG, OPTIMIZE, DEPRECATED)

PRIORITY: dict[str, int] = {
    BUG: 5,
    FIXME: 4,
    HACK: 3,
    XXX: 3,
    DEPRECATED: 2,
    OPTIMIZE: 2,
    TODO: 1,
    REVIEW: 1,
    NOTE: 0,
}


@dataclass(frozen=True, slots=True)
class Todo:
    tag: str
    text: str
    owner: str | None
    file: str
    line: int
    in_comment: bool


_GENERIC_MARKERS: tuple[str, ...] = ("//", "#", "/*", "*", "<!--", "--", ";", "%")
_UNIVERSAL_MARKERS: tuple[str, ...] = ("/*", "*", "<!--")

# A character that makes surrounding text "prose" rather than punctuation.
_PROSE = re.compile(r"[^\s\W\d_]")
_BARE_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\[[ xX]\])?\s*$")


def _has_prose(text: str) -> bool:
    return text == "" or _PROSE.search(text) is not None


def _trailing_is_decoration(trailing: str) -> bool:
    return _PROSE.search(trailing) is None


def _marker_context(
    line: str, tag_start: int, line_comment: str, *, allow_bare_line: bool
) -> tuple[bool, bool]:
    """Return ``(accepted, in_comment)`` for a match at ``tag_start``."""
    before = line[:tag_start]
    markers = (*([line_comment] if line_comment else []), *_UNIVERSAL_MARKERS) or _GENERIC_MARKERS

    last_index = -1
    last_length = 0
    for marker in markers:
        if marker == "":
            continue
        index = before.rfind(marker)
        if index > last_index:
            last_index = index
            last_length = len(marker)

    if last_index >= 0 and _trailing_is_decoration(before[last_index + last_length :]):
        return True, True

    # A marker on a bare line counts in prose (Markdown task lists, plain-text
    # notes) but not in source: `BUG = "BUG"` and `BUG: 5, FIXME: 4` in a
    # constant table are not debt.
    if allow_bare_line and _BARE_LINE.match(before):
        return True, False

    return False, False


def build_pattern(tags: tuple[str, ...], *, case_sensitive: bool = True) -> re.Pattern[str]:
    alternation = "|".join(tags)
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(
        rf"\b(?P<tag>{alternation})\b(?:\s*\((?P<owner>[^)]{{0,60}})\))?\s*[:\-]?\s*(?P<text>.*)$",
        flags,
    )


def scan(
    rel: str,
    text: str,
    line_comment: str = "",
    *,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    case_sensitive: bool = True,
    allow_bare_line: bool = False,
) -> list[Todo]:
    """Find debt markers in one file's content.

    ``allow_bare_line`` should be true only for prose files (Markdown and
    friends). Enabling it for source files makes constant tables such as
    ``BUG = "BUG"`` report themselves as debt.
    """
    if not tags:
        return []

    pattern = build_pattern(tags, case_sensitive=case_sensitive)
    hits: list[Todo] = []

    for number, line in enumerate(text.splitlines(), start=1):
        if "todo" not in line.lower() and not any(
            tag.lower() in line.lower() for tag in tags if tag.lower() != "todo"
        ):
            continue

        match = pattern.search(line)
        if match is None:
            continue

        tag = match.group("tag").upper()
        if tag not in ALL_TAGS:
            continue

        accepted, in_comment = _marker_context(
            line, match.start(), line_comment, allow_bare_line=allow_bare_line
        )
        if not accepted:
            continue

        body = (match.group("text") or "").strip()
        if not _has_prose(body):
            continue

        owner = (match.group("owner") or "").strip()
        hits.append(
            Todo(
                tag=tag,
                text=truncate(body, 200),
                owner=owner or None,
                file=rel,
                line=number,
                in_comment=in_comment,
            )
        )

    return hits


def sort_key(hit: Todo) -> tuple[int, str, int]:
    return (-PRIORITY.get(hit.tag, 0), hit.file, hit.line)
