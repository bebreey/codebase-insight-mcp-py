"""String literal blanking, the reason test data is not reported as debt."""

from __future__ import annotations

from codebase_insight.core import masking, todos


def test_blanks_a_python_string_literal() -> None:
    source = 'MARKER = "# FIXME(alice): overflow here"\nvalue = 1\n'
    masked = masking.mask_string_literals(source, "Python")

    assert masked.count("\n") == source.count("\n")
    assert len(masked.splitlines()[0]) == len(source.splitlines()[0])
    assert "FIXME" not in masked
    assert "MARKER = " in masked


def test_preserves_line_numbers_for_multiline_strings() -> None:
    source = 'DOC = """\nline two\nTODO: not real debt\n"""\nafter = 1\n'
    masked = masking.mask_string_literals(source, "Python")

    assert masked.count("\n") == source.count("\n")
    assert masked.splitlines()[4] == "after = 1"
    assert "TODO" not in masked


def test_blanks_a_whole_f_string() -> None:
    """CPython reports an f-string's inner constants with the span of the whole
    f-string, so the expression parts are blanked as well.

    That is fine for this purpose — an f-string is a string, and a marker inside
    one is text rather than debt. The behaviour is pinned here so it stays a
    decision instead of becoming an accident.
    """
    source = 'label = f"prefix {compute()} TODO: still inside"\n'
    masked = masking.mask_string_literals(source, "Python")

    assert "TODO" not in masked
    assert len(masked.splitlines()[0]) == len(source.splitlines()[0])
    assert masked.splitlines()[0].startswith("label = ")


def test_handles_non_ascii_before_the_literal() -> None:
    """ast column offsets are byte offsets, so a multi-byte prefix must not shift the span."""
    source = 'label = "中文前缀" + "# TODO: inside a literal"\n'
    masked = masking.mask_string_literals(source, "Python")
    assert "中文前缀" not in masked
    assert "TODO" not in masked
    assert len(masked.splitlines()[0]) == len(source.splitlines()[0])


def test_leaves_comments_untouched() -> None:
    source = "# TODO: this is real debt\n"
    assert masking.mask_string_literals(source, "Python") == source


def test_returns_other_languages_and_broken_python_unchanged() -> None:
    typescript = 'const marker = "# TODO: text";\n'
    assert masking.mask_string_literals(typescript, "TypeScript") == typescript

    broken = 'x = "# TODO"\nif (\n'
    assert masking.mask_string_literals(broken, "Python") == broken


def test_a_marker_in_a_string_is_not_reported_by_the_scanner() -> None:
    source = 'assert todos.scan("a.py", "# FIXME(alice): overflow here\\n", "#") == []\n'
    masked = masking.mask_string_literals(source, "Python")
    assert todos.scan("a.py", masked, "#") == []
    # Without the blanking the same line is a false positive.
    assert len(todos.scan("a.py", source, "#")) == 1
