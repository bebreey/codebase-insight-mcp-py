"""Symbol extraction.

Two strategies, chosen per language because they answer different questions:

* **Python** is parsed with the standard library ``ast`` module. An AST gives
  exact line numbers and real signatures, and nested definitions are classified
  correctly (a ``def`` inside a class is a method, a ``def`` inside that method
  is a function). A file that does not parse falls back to the regex rules so a
  half-finished module still yields something useful.
* **Everything else** uses line-oriented regex rules. That keeps the runtime
  dependency surface at two packages and works on code that does not compile,
  at the cost of only recognising single-line signatures.

The TypeScript implementation of this server had to use regex for Python too;
``ast`` is the reason this version can be exact where it matters most.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

from .text import truncate

FUNCTION = "function"
METHOD = "method"
CLASS = "class"
INTERFACE = "interface"
STRUCT = "struct"
TRAIT = "trait"
ENUM = "enum"
TYPE_ALIAS = "type"
CONSTANT = "constant"
MODULE = "module"
EXPORT = "export"

ALL_KINDS: tuple[str, ...] = (
    FUNCTION,
    METHOD,
    CLASS,
    INTERFACE,
    STRUCT,
    TRAIT,
    ENUM,
    TYPE_ALIAS,
    CONSTANT,
    MODULE,
    EXPORT,
)


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    language: str
    file: str
    line: int
    signature: str


# --------------------------------------------------------------------------- #
# Python: standard-library AST
# --------------------------------------------------------------------------- #


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.symbols: list[Symbol] = []
        self._class_depth = 0
        self._function_depth = 0

    def _emit(self, node: ast.AST, kind: str, signature: str, name: str | None = None) -> None:
        # `name` is explicit because ast.Assign carries no `.name` attribute:
        # reading it via getattr silently dropped every module-level constant.
        resolved = name if name is not None else getattr(node, "name", None)
        if not isinstance(resolved, str):
            return
        self.symbols.append(
            Symbol(
                name=resolved,
                kind=kind,
                language="Python",
                file=self.rel,
                line=getattr(node, "lineno", 0),
                signature=truncate(signature, 160),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = ", ".join(_safe_unparse(base) for base in node.bases)
        self._emit(node, CLASS, f"class {node.name}({bases})" if bases else f"class {node.name}")
        self._class_depth += 1
        self.generic_visit(node)
        self._class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, "def")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, "async def")

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, keyword: str) -> None:
        kind = METHOD if (self._class_depth > 0 and self._function_depth == 0) else FUNCTION
        signature = f"{keyword} {node.name}({_safe_unparse(node.args)})"
        if node.returns is not None:
            signature += f" -> {_safe_unparse(node.returns)}"
        self._emit(node, kind, signature)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._class_depth == 0 and self._function_depth == 0:
            for target in node.targets:
                self._maybe_constant(target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._class_depth == 0 and self._function_depth == 0 and node.value is not None:
            self._maybe_constant(node.target, node)
        self.generic_visit(node)

    def _maybe_constant(self, target: ast.expr, node: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        if target.id == "__all__":
            self._emit(node, EXPORT, "__all__ = [...]", name=target.id)
            return
        if len(target.id) > 2 and target.id.isupper():
            self._emit(node, CONSTANT, f"{target.id} = ...", name=target.id)


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, RecursionError):
        return "..."


def _python_via_ast(rel: str, text: str) -> list[Symbol] | None:
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError, RecursionError):
        return None
    visitor = _PythonVisitor(rel)
    visitor.visit(tree)
    visitor.symbols.sort(key=lambda symbol: symbol.line)
    return visitor.symbols


# --------------------------------------------------------------------------- #
# Other languages: line-oriented rules
# --------------------------------------------------------------------------- #

_TS_METHOD_KEYWORDS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "new",
        "throw",
        "else",
        "do",
        "try",
        "assert",
        "break",
        "continue",
        "yield",
        "await",
        "using",
        "typeof",
        "delete",
        "void",
        "in",
        "of",
        "case",
        "with",
        "super",
        "this",
        "export",
        "import",
        "function",
        "constructor",
    }
)

Refine = Callable[[re.Match[str]], "str | None"]

# Refine sentinel: "this match is real, and the rule's own kind stands".
KEEP = "__keep__"


@dataclass(frozen=True, slots=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    refine: Refine | None = None


def _indented_becomes(kind: str) -> Refine:
    """A refine that promotes indented matches to ``kind``.

    Returning ``KEEP`` rather than the kind itself matters: ``None`` from a
    refine means "discard this match", so a rule that should keep its own kind
    has to say so explicitly.
    """

    def refine(match: re.Match[str]) -> str | None:
        return kind if re.match(r"^[ \t]", match.group(0)) else KEEP

    return refine


def _module_level_only(match: re.Match[str]) -> str | None:
    return KEEP if not re.match(r"^[ \t]", match.group(0)) else None


def _typedscript_rules() -> tuple[_Rule, ...]:
    modifiers = r"(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|abstract\s+|async\s+|declare\s+)*"
    return (
        _Rule(
            CLASS,
            re.compile(
                r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"
            ),
        ),
        _Rule(INTERFACE, re.compile(r"^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)")),
        _Rule(ENUM, re.compile(r"^\s*(?:export\s+)?(?:const\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)")),
        _Rule(TYPE_ALIAS, re.compile(r"^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*[=<]")),
        _Rule(
            FUNCTION,
            re.compile(
                r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)"
            ),
            _indented_becomes(METHOD),
        ),
        _Rule(
            CONSTANT,
            re.compile(r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*="),
            _module_level_only,
        ),
        _Rule(
            METHOD,
            re.compile(
                rf"^\s{{2,}}{modifiers}(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^;{{}}]*\)\s*(?::[^{{;]+)?\s*\{{"
            ),
            lambda m: None if _is_statement(m) else METHOD,
        ),
        _Rule(
            METHOD,
            re.compile(
                rf"^\s{{2,}}{modifiers}(?P<name>[A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"
            ),
            lambda m: None if _is_statement(m) else METHOD,
        ),
    )


def _is_statement(match: re.Match[str]) -> bool:
    head = re.match(r"\s*([A-Za-z_$][\w$]*)", match.group(0))
    return head is None or head.group(1) in _TS_METHOD_KEYWORDS


_JVM_MODIFIERS = (
    r"(?:public\s+|private\s+|protected\s+|internal\s+|final\s+|abstract\s+|sealed\s+|static\s+"
    r"|partial\s+|open\s+|data\s+|value\s+|override\s+|virtual\s+|async\s+|suspend\s+|inline\s+"
    r"|operator\s+|extern\s+|unsafe\s+|native\s+|synchronized\s+|readonly\s+|ref\s+|new\s+)*"
)


def _jvm_rules(language: str) -> tuple[_Rule, ...]:
    rules: list[_Rule] = [
        _Rule(CLASS, re.compile(rf"^\s*{_JVM_MODIFIERS}class\s+(?P<name>\w+)")),
        _Rule(INTERFACE, re.compile(rf"^\s*{_JVM_MODIFIERS}interface\s+(?P<name>\w+)")),
        _Rule(ENUM, re.compile(rf"^\s*{_JVM_MODIFIERS}enum\s+(?P<name>\w+)")),
        _Rule(STRUCT, re.compile(rf"^\s*{_JVM_MODIFIERS}struct\s+(?P<name>\w+)")),
        _Rule(TYPE_ALIAS, re.compile(rf"^\s*{_JVM_MODIFIERS}(?:record|annotation)\s+(?P<name>\w+)")),
    ]
    if language == "Kotlin":
        rules.append(
            _Rule(
                FUNCTION,
                re.compile(
                    r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|open\s+|override\s+|abstract\s+|suspend\s+|inline\s+|operator\s+|tailrec\s+|external\s+|final\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w<>,.?]+\.)?(?P<name>\w+)"
                ),
            )
        )
    rules.append(
        _Rule(
            METHOD,
            re.compile(rf"^\s*{_JVM_MODIFIERS}[\w<>\[\],.?]+\s+(?P<name>\w+)\s*\("),
            lambda m: None if _is_statement(m) else METHOD,
        )
    )
    return tuple(rules)


_RULES: dict[str, tuple[_Rule, ...]] = {
    "TypeScript": _typedscript_rules(),
    "JavaScript": _typedscript_rules(),
    "Go": (
        # A receiver in the signature is what makes a Go function a method.
        _Rule(
            FUNCTION,
            re.compile(r"^func\s+(?:\((?P<receiver>[^)]*)\)\s*)?(?P<name>\w+)"),
            lambda match: METHOD if match.group("receiver") else KEEP,
        ),
        _Rule(STRUCT, re.compile(r"^type\s+(?P<name>\w+)\s+struct\b")),
        _Rule(INTERFACE, re.compile(r"^type\s+(?P<name>\w+)\s+interface\b")),
        _Rule(TYPE_ALIAS, re.compile(r"^type\s+(?P<name>\w+)\s+")),
        _Rule(CONSTANT, re.compile(r"^(?:const|var)\s+(?P<name>\w+)")),
    ),
    "Rust": (
        _Rule(
            FUNCTION,
            re.compile(
                r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+(?P<name>\w+)"
            ),
            _indented_becomes(METHOD),
        ),
        _Rule(STRUCT, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+(?P<name>\w+)")),
        _Rule(ENUM, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(?P<name>\w+)")),
        _Rule(TRAIT, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?trait\s+(?P<name>\w+)")),
        _Rule(TYPE_ALIAS, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?type\s+(?P<name>\w+)")),
        _Rule(MODULE, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>\w+)")),
        _Rule(CONSTANT, re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+(?P<name>\w+)")),
    ),
    "Ruby": (
        _Rule(CLASS, re.compile(r"^\s*class\s+(?P<name>[A-Z]\w*(?:::\w+)*)")),
        _Rule(MODULE, re.compile(r"^\s*module\s+(?P<name>[A-Z]\w*(?:::\w+)*)")),
        _Rule(METHOD, re.compile(r"^\s*def\s+(?P<name>[\w?!=.\[\]]+)")),
    ),
    "PHP": (
        _Rule(CLASS, re.compile(r"^\s*(?:final\s+|abstract\s+)*class\s+(?P<name>\w+)")),
        _Rule(INTERFACE, re.compile(r"^\s*interface\s+(?P<name>\w+)")),
        _Rule(TRAIT, re.compile(r"^\s*trait\s+(?P<name>\w+)")),
        _Rule(ENUM, re.compile(r"^\s*enum\s+(?P<name>\w+)")),
        _Rule(
            FUNCTION,
            re.compile(
                r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+)*function\s+(?P<name>\w+)"
            ),
        ),
    ),
    "C": (
        _Rule(STRUCT, re.compile(r"^\s*(?:typedef\s+)?struct\s+(?P<name>\w+)")),
        _Rule(ENUM, re.compile(r"^\s*(?:typedef\s+)?enum\s+(?P<name>\w+)")),
        _Rule(TYPE_ALIAS, re.compile(r"^\s*typedef\b[^;]*?\(?\*?\s*(?P<name>\w+)\s*\)?\s*;")),
    ),
    "Shell": (
        _Rule(FUNCTION, re.compile(r"^\s*function\s+(?P<name>[\w.-]+)")),
        _Rule(FUNCTION, re.compile(r"^\s*(?P<name>[\w.-]+)\s*\(\s*\)\s*\{")),
    ),
    "SQL": (
        _Rule(
            TYPE_ALIAS,
            re.compile(
                r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW|FUNCTION|PROCEDURE|TRIGGER|INDEX|SCHEMA|TYPE|SEQUENCE)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w.\"`\[\]]+)",
                re.IGNORECASE,
            ),
        ),
    ),
    "Terraform": (
        _Rule(MODULE, re.compile(r"^(?:resource|data|module)\s+\"(?P<name>[^\"]+)\"")),
        _Rule(CONSTANT, re.compile(r"^(?:variable|output|local)\s+\"(?P<name>[^\"]+)\"")),
    ),
}
_RULES["C++"] = (
    _Rule(CLASS, re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?class\s+(?P<name>\w+)")),
    *_RULES["C"],
    _Rule(MODULE, re.compile(r"^\s*namespace\s+(?P<name>\w+)")),
)
for _jvm in ("Java", "Kotlin", "C#", "Scala"):
    _RULES.setdefault(_jvm, _jvm_rules(_jvm))
del _jvm


def supported_languages() -> tuple[str, ...]:
    return tuple(sorted({*_RULES, "Python"}))


def _apply_rules(rel: str, language: str, text: str) -> list[Symbol]:
    rules = _RULES.get(language)
    if rules is None:
        return []

    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "":
            continue
        for rule in rules:
            match = rule.pattern.match(line)
            if match is None:
                continue
            kind = rule.kind
            if rule.refine is not None:
                refined = rule.refine(match)
                if refined is None:
                    break  # first matching rule wins for this line
                if refined != KEEP:
                    kind = refined
            name = match.group("name")
            if name:
                symbols.append(
                    Symbol(
                        name=name,
                        kind=kind,
                        language=language,
                        file=rel,
                        line=number,
                        signature=truncate(stripped, 160),
                    )
                )
            break
    return symbols


def extract_symbols(rel: str, text: str, language: str) -> list[Symbol]:
    """Extract declarations from one file's content."""
    if language == "Python":
        via_ast = _python_via_ast(rel, text)
        if via_ast is not None:
            return via_ast
        # Unparseable Python still gets a regex pass so a work-in-progress file
        # is not silently empty.
        return _python_via_regex(rel, text)
    return _apply_rules(rel, language, text)


_PY_REGEX = (
    _Rule(CLASS, re.compile(r"^\s*class\s+(?P<name>\w+)")),
    _Rule(
        FUNCTION,
        re.compile(r"^(?P<indent>[ \t]*)(?:async\s+)?def\s+(?P<name>\w+)"),
        lambda m: METHOD if m.group("indent") else FUNCTION,
    ),
    _Rule(CONSTANT, re.compile(r"^(?P<name>[A-Z][A-Z0-9_]{2,})\s*(?::[^=]+)?=")),
    _Rule(EXPORT, re.compile(r"^(?P<name>__all__)\s*(?::[^=]+)?=")),
)


def _python_via_regex(rel: str, text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        for rule in _PY_REGEX:
            match = rule.pattern.match(line)
            if match is None:
                continue
            kind = rule.refine(match) if rule.refine else rule.kind
            symbols.append(
                Symbol(
                    name=match.group("name"),
                    kind=kind or rule.kind,
                    language="Python",
                    file=rel,
                    line=number,
                    signature=truncate(stripped, 160),
                )
            )
            break
    return symbols
