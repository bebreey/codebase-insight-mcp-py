"""Tech-debt marker scanning, including the false positives found in testing."""

from __future__ import annotations

from codebase_insight.core import todos


def test_finds_a_trailing_comment_marker() -> None:
    hits = todos.scan("a.py", "value = 1  # TODO: extract this\n", "#")
    assert len(hits) == 1
    assert hits[0].tag == "TODO"
    assert hits[0].text == "extract this"
    assert hits[0].owner is None
    assert hits[0].line == 1
    assert hits[0].in_comment is True


def test_captures_an_owner() -> None:
    hits = todos.scan("a.py", "# FIXME(alice): overflow here\n", "#")
    assert hits[0].tag == "FIXME"
    assert hits[0].owner == "alice"
    assert hits[0].text == "overflow here"


def test_accepts_a_markdown_task_item_only_in_prose_files() -> None:
    line = "- [ ] TODO: add screenshots\n"
    assert len(todos.scan("notes.md", line, "", allow_bare_line=True)) == 1
    # The same line in a source file is not a marker.
    assert todos.scan("a.py", line, "#") == []


def test_bare_line_markers_are_rejected_in_source() -> None:
    """Regression: a constant table reported itself as debt.

    ``BUG = "BUG"`` and ``BUG: 5, FIXME: 4`` sit on bare lines and their text
    contains prose, so only the prose-file restriction keeps them out.
    """
    assert todos.scan("a.py", 'BUG = "BUG"\n', "#") == []
    assert todos.scan("a.py", "    BUG: 5, FIXME: 4, HACK: 3,\n", "#") == []


def test_does_not_match_source_literals() -> None:
    assert todos.scan("a.py", "TAGS = ['BUG', 'FIXME']\n", "#") == []
    assert todos.scan("a.py", 'message = "Triage the FIXME and BUG markers"\n', "#") == []


def test_does_not_match_prose_that_mentions_the_syntax() -> None:
    line = "  # The rule stops `TODOList` from matching while allowing `TODO:` here\n"
    assert todos.scan("a.py", line, "#") == []


def test_rejects_a_marker_whose_text_is_only_punctuation_or_digits() -> None:
    assert todos.scan("a.py", "    BUG: 5,\n", "#") == []


def test_is_case_sensitive_by_default() -> None:
    assert todos.scan("a.py", "# todo: lower case\n", "#") == []
    assert len(todos.scan("a.py", "# todo: lower case\n", "#", case_sensitive=False)) == 1


def test_honours_a_custom_tag_set() -> None:
    assert len(todos.scan("a.py", "# NOTE: keep this\n", "#", tags=("NOTE",))) == 1
    assert todos.scan("a.py", "# NOTE: keep this\n", "#") == []


def test_sorts_the_most_urgent_tag_first() -> None:
    hits = todos.scan("a.py", "# TODO: a\n# BUG: b\n# FIXME: c\n", "#")
    ordered = sorted(hits, key=todos.sort_key)
    assert [hit.tag for hit in ordered] == ["BUG", "FIXME", "TODO"]


def test_default_tags_exclude_note() -> None:
    assert "FIXME" in todos.DEFAULT_TAGS
    assert "NOTE" not in todos.DEFAULT_TAGS
    assert set(todos.DEFAULT_TAGS) <= set(todos.ALL_TAGS)
