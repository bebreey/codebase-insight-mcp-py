"""Language table and line counting."""

from __future__ import annotations

from codebase_insight.core import languages, loc


def test_common_extensions_map_to_languages() -> None:
    assert languages.language_of("a.py").name == "Python"
    assert languages.language_of("b.tsx").name == "TypeScript"
    assert languages.language_of("c.go").name == "Go"
    assert languages.language_of("d.rs").name == "Rust"
    assert languages.language_of("e.java").name == "Java"


def test_paths_are_matched_on_the_basename_and_case_insensitively() -> None:
    assert languages.language_of("SRC/App.TSX").name == "TypeScript"
    assert languages.language_of(r"src\core\mod.PY").name == "Python"


def test_filenames_without_extensions_are_recognised() -> None:
    assert languages.language_of("Makefile").name == "Makefile"
    assert languages.language_of("Dockerfile").name == "Dockerfile"
    # Dotfiles have no extension: `Path.suffix` is empty when the only dot leads.
    assert languages.language_of(".gitignore").name == "Git Config"
    assert languages.language_of(".env").name == "Env"


def test_unknown_and_binary_types_return_none() -> None:
    assert languages.language_of("logo.png") is None
    assert languages.language_of("mystery.unknownext") is None
    assert languages.language_of("LICENSE") is None
    assert languages.has_binary_extension("logo.png") is True
    assert languages.has_binary_extension("a.py") is False


def test_kind_separates_code_from_config() -> None:
    assert languages.language_of("a.py").kind == languages.CODE
    assert languages.language_of("a.json").kind == languages.DATA
    assert languages.language_of("a.md").kind == languages.DOC
    assert languages.is_code("a.py") is True
    assert languages.is_code("a.json") is False


def test_generated_filenames_are_flagged() -> None:
    assert languages.is_generated("poetry.lock") is True
    assert languages.is_generated("package-lock.json") is True
    assert languages.is_generated("pyproject.toml") is False


def test_line_counting_separates_blank_comment_and_code() -> None:
    source = "// comment\n\nconst x = 1;\n/* block\n   still block */\nconst y = 2;\n"
    stats = loc.count_lines("example.ts", source)

    assert stats.lines == 6
    assert stats.non_blank == 5
    assert stats.comment == 3
    assert stats.code == 2


def test_line_counting_uses_the_language_comment_prefix() -> None:
    python = loc.count_lines("a.py", "# comment\nvalue = 1\n")
    assert (python.comment, python.code) == (1, 1)

    # `#` is not a comment in TypeScript, so only the code line counts.
    typescript = loc.count_lines("a.ts", 'const hash = "# not a comment";\n')
    assert typescript.comment == 0


def test_split_lines_handles_crlf_bom_and_trailing_newline() -> None:
    assert loc.split_lines("a\nb\n") == ["a", "b"]
    assert loc.split_lines("a\nb") == ["a", "b"]
    assert loc.split_lines("") == []
    assert loc.split_lines("\ufeffa\r\nb\r\n") == ["a", "b"]


def test_loc_tracks_the_longest_line_and_can_be_summed() -> None:
    long_line = loc.count_lines("a.ts", "a\n" + "x" * 50)
    assert long_line.max_line_length == 50

    combined = loc.add(loc.count_lines("a.ts", "a\n"), loc.count_lines("a.ts", "b\nc\n"))
    assert combined.lines == 3


def test_every_advertised_extension_resolves_to_its_own_language() -> None:
    """Table integrity.

    A single missing comma turns ``("toml")`` into a string, so the registration
    loop walks its characters and registers ``t``/``o``/``m``/``l`` instead.
    Nothing else in the suite noticed; the TOML column simply vanished from the
    language statistics while the code still read correctly.
    """
    mapping = languages.extension_map()
    assert len(mapping) > 60

    for extension, name in mapping.items():
        resolved = languages.language_of(f"sample.{extension}")
        assert resolved is not None, f".{extension} is advertised but resolves to nothing"
        assert resolved.name == name, f".{extension} resolves to {resolved.name}, expected {name}"


def test_only_known_single_character_extensions_are_registered() -> None:
    """Regression for the missing-comma bug.

    ``("toml")`` is not a tuple, so the registration loop walks its characters
    and registers ``t``/``o``/``m``/``l``. ``c``, ``h`` and ``r`` are the only
    genuine single-character extensions in the table.
    """
    singles = {extension for extension in languages.extension_map() if len(extension) == 1}
    assert singles == {"c", "h", "r"}


def test_real_extensions_that_the_bug_used_to_break() -> None:
    assert languages.language_of("script.r").name == "R"
    assert languages.language_of("Cargo.toml").name == "TOML"
    assert languages.language_of("pyproject.toml").name == "TOML"
    assert languages.language_of("page.astro").name == "Astro"

    # Single letters belong to no language.
    for bogus in ("x.a", "x.s", "x.o", "x.m", "x.l"):
        assert languages.language_of(bogus) is None, bogus


def test_extension_map_matches_language_of() -> None:
    assert languages.extension_map()["py"] == "Python"
    assert languages.extension_map()["tsx"] == "TypeScript"
    assert languages.extension_map()["toml"] == "TOML"
    assert languages.extension_map()["astro"] == "Astro"
