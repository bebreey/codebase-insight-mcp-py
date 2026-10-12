"""Symbol extraction: the AST path for Python, regex rules elsewhere."""

from __future__ import annotations

from codebase_insight.core import symbols

PYTHON_SAMPLE = '''
"""Module docstring."""

MAX_RETRIES = 3
__all__ = ["Service"]


class Service:
    """A service."""

    def start(self, port: int = 8000) -> None:
        def retry(times: int) -> int:
            return times

        self._retry = retry

    async def stop(self) -> bool:
        return True


def main(argv: list[str]) -> int:
    return 0
'''


def test_ast_classifies_class_method_nested_function_and_function() -> None:
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("a.py", PYTHON_SAMPLE, "Python")}

    assert found["Service"] == symbols.CLASS
    assert found["start"] == symbols.METHOD
    assert found["stop"] == symbols.METHOD
    # A `def` nested inside a method is a function, not a second method.
    assert found["retry"] == symbols.FUNCTION
    assert found["main"] == symbols.FUNCTION
    assert found["MAX_RETRIES"] == symbols.CONSTANT
    assert found["__all__"] == symbols.EXPORT


def test_ast_reports_exact_line_numbers_and_real_signatures() -> None:
    found = {symbol.name: symbol for symbol in symbols.extract_symbols("a.py", PYTHON_SAMPLE, "Python")}

    assert found["Service"].line == 8
    assert found["start"].line == 11
    assert found["retry"].line == 12
    assert found["stop"].line == 17
    assert found["main"].line == 21
    assert "port: int=8000" in found["start"].signature.replace(" = ", "=")
    assert "-> None" in found["start"].signature
    assert found["stop"].signature.startswith("async def stop")


def test_ast_handles_decorated_and_nested_classes() -> None:
    source = "class Outer:\n    class Inner:\n        pass\n\n\nclass Plain:\n    pass\n"
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("a.py", source, "Python")}
    assert found["Outer"] == symbols.CLASS
    assert found["Inner"] == symbols.CLASS
    assert found["Plain"] == symbols.CLASS


def test_unparseable_python_falls_back_to_regex() -> None:
    broken = "class Half:\n    def done(self):\n        return (\n"
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("broken.py", broken, "Python")}
    assert found["Half"] == symbols.CLASS
    assert found["done"] == symbols.METHOD


def test_local_constants_are_not_reported_in_python() -> None:
    source = "def run() -> None:\n    local = 42\n    print(local)\n"
    names = [symbol.name for symbol in symbols.extract_symbols("a.py", source, "Python")]
    assert names == ["run"]


def test_go_receiver_makes_a_method() -> None:
    """Regression: the receiver group was matched but never interpreted."""
    source = (
        "package main\n\n"
        "type Config struct {\n\tName string\n}\n\n"
        "func New() *Config { return nil }\n\n"
        "func (c *Config) Load() error { return nil }\n"
    )
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("a.go", source, "Go")}
    assert found["Config"] == symbols.STRUCT
    assert found["New"] == symbols.FUNCTION
    assert found["Load"] == symbols.METHOD


def test_top_level_typescript_function_is_not_dropped() -> None:
    """Regression: a refine returned None, which means "discard the match"."""
    source = "export class Circle {}\nexport function make(): void {}\nexport const SCALE = 2;\n"
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("a.ts", source, "TypeScript")}
    assert found["Circle"] == symbols.CLASS
    assert found["make"] == symbols.FUNCTION
    assert found["SCALE"] == symbols.CONSTANT


def test_typescript_indented_bindings_are_not_constants() -> None:
    source = "export function run(): void {\n  const local = 1;\n}\n"
    names = [symbol.name for symbol in symbols.extract_symbols("a.ts", source, "TypeScript")]
    assert "run" in names
    assert "local" not in names


def test_rust_items() -> None:
    source = (
        "pub struct Engine {}\npub trait Runnable {}\npub enum State { Idle }\npub fn boot() -> Engine {}\n"
    )
    found = {symbol.name: symbol.kind for symbol in symbols.extract_symbols("a.rs", source, "Rust")}
    assert found["Engine"] == symbols.STRUCT
    assert found["Runnable"] == symbols.TRAIT
    assert found["State"] == symbols.ENUM
    assert found["boot"] == symbols.FUNCTION


def test_unknown_language_yields_nothing_and_python_is_supported() -> None:
    assert symbols.extract_symbols("a.xyz", "whatever", "Unknown") == []
    assert "Python" in symbols.supported_languages()
    assert "Go" in symbols.supported_languages()
    assert len(symbols.supported_languages()) >= 14


def test_empty_python_file_is_handled() -> None:
    assert symbols.extract_symbols("empty.py", "", "Python") == []
