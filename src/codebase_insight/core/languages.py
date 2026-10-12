"""Extension to language mapping.

Hand-written rather than pulled from ``pygments``/``linguist``: the whole table
is reviewable on one screen and adds no dependency. ``kind`` matters for the
metrics, so a repository full of JSON fixtures does not look like a large
codebase.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE = "code"
MARKUP = "markup"
STYLE = "style"
DATA = "data"
CONFIG = "config"
DOC = "doc"


@dataclass(frozen=True, slots=True)
class Language:
    name: str
    kind: str
    line_comment: str = ""


# (name, kind, line comment, extensions)
_TABLE: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Python", CODE, "#", ("py", "pyi", "pyw")),
    ("TypeScript", CODE, "//", ("ts", "tsx", "mts", "cts")),
    ("JavaScript", CODE, "//", ("js", "jsx", "mjs", "cjs")),
    ("Go", CODE, "//", ("go",)),
    ("Rust", CODE, "//", ("rs",)),
    ("Java", CODE, "//", ("java",)),
    ("Kotlin", CODE, "//", ("kt", "kts")),
    ("C#", CODE, "//", ("cs",)),
    ("C++", CODE, "//", ("cpp", "cc", "cxx", "hpp", "hh", "hxx")),
    ("C", CODE, "//", ("c", "h")),
    ("Swift", CODE, "//", ("swift",)),
    ("Ruby", CODE, "#", ("rb", "rake", "gemspec")),
    ("PHP", CODE, "//", ("php",)),
    ("Scala", CODE, "//", ("scala", "sc")),
    ("Dart", CODE, "//", ("dart",)),
    ("Zig", CODE, "//", ("zig",)),
    ("Julia", CODE, "#", ("jl",)),
    ("R", CODE, "#", ("r",)),
    ("Perl", CODE, "#", ("pl", "pm")),
    ("Lua", CODE, "--", ("lua",)),
    ("Haskell", CODE, "--", ("hs",)),
    ("Elixir", CODE, "#", ("ex", "exs")),
    ("Clojure", CODE, ";", ("clj", "cljs", "cljc")),
    ("Shell", CODE, "#", ("sh", "bash", "zsh", "fish", "ksh")),
    ("PowerShell", CODE, "#", ("ps1", "psm1", "psd1")),
    ("Batch", CODE, "REM", ("bat", "cmd")),
    ("SQL", CODE, "--", ("sql",)),
    ("Terraform", CODE, "#", ("tf", "tfvars")),
    ("Protobuf", CODE, "//", ("proto",)),
    ("GraphQL", CODE, "#", ("graphql", "gql")),
    ("Solidity", CODE, "//", ("sol",)),
    ("HTML", MARKUP, "", ("html", "htm")),
    ("Vue", MARKUP, "//", ("vue",)),
    ("Svelte", MARKUP, "//", ("svelte",)),
    ("Astro", MARKUP, "//", ("astro",)),
    ("XML", MARKUP, "", ("xml", "xsd", "xsl", "svg")),
    ("CSS", STYLE, "", ("css",)),
    ("SCSS", STYLE, "//", ("scss", "sass")),
    ("Less", STYLE, "//", ("less",)),
    ("JSON", DATA, "", ("json", "jsonc", "json5")),
    ("YAML", DATA, "#", ("yaml", "yml")),
    ("TOML", DATA, "#", ("toml",)),
    ("CSV", DATA, "", ("csv", "tsv")),
    ("INI", CONFIG, ";", ("ini", "cfg", "conf", "properties")),
    ("Env", CONFIG, "#", ("env",)),
    ("Git Config", CONFIG, "#", ("gitignore", "gitattributes", "dockerignore")),
    ("Markdown", DOC, "", ("md", "markdown")),
    ("reStructuredText", DOC, "", ("rst",)),
    ("LaTeX", DOC, "%", ("tex", "sty")),
    ("Jupyter Notebook", DOC, "#", ("ipynb",)),
)

_BY_EXTENSION: dict[str, Language] = {}
_BY_NAME: dict[str, Language] = {}

for _name, _kind, _comment, _exts in _TABLE:
    _language = Language(name=_name, kind=_kind, line_comment=_comment)
    _BY_NAME[_name] = _language
    for _ext in _exts:
        _BY_EXTENSION[_ext] = _language
del _name, _kind, _comment, _exts, _language, _ext

# Filenames recognised regardless of extension. Dotfiles have to be listed
# here: `Path.suffix` is empty when the only dot is the leading one.
SPECIAL_FILENAMES: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "cmakelists.txt": "CMake",
    "go.mod": "Go Module",
    "go.sum": "Go Module",
    "gemfile": "Ruby",
    "rakefile": "Ruby",
    "vagrantfile": "Ruby",
    "procfile": "Config",
    ".gitignore": "Git Config",
    ".gitattributes": "Git Config",
    ".dockerignore": "Git Config",
    ".editorconfig": "INI",
    ".env": "Env",
    ".babelrc": "JSON",
    ".eslintrc": "JSON",
    ".prettierrc": "JSON",
}

_SYNTHETIC: tuple[tuple[str, str, str], ...] = (
    ("Dockerfile", CONFIG, "#"),
    ("Makefile", CONFIG, "#"),
    ("CMake", CONFIG, "#"),
    ("Go Module", CONFIG, "//"),
)
for _n, _k, _c in _SYNTHETIC:
    _BY_NAME.setdefault(_n, Language(name=_n, kind=_k, line_comment=_c))
del _n, _k, _c

BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "bmp",
        "ico",
        "webp",
        "avif",
        "tiff",
        "psd",
        "mp3",
        "wav",
        "ogg",
        "flac",
        "aac",
        "m4a",
        "mp4",
        "mov",
        "avi",
        "mkv",
        "webm",
        "zip",
        "tar",
        "gz",
        "tgz",
        "bz2",
        "xz",
        "7z",
        "rar",
        "jar",
        "war",
        "whl",
        "deb",
        "rpm",
        "dmg",
        "iso",
        "exe",
        "dll",
        "so",
        "dylib",
        "bin",
        "o",
        "obj",
        "a",
        "lib",
        "class",
        "pyc",
        "pyo",
        "pdb",
        "wasm",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "odt",
        "ods",
        "epub",
        "ttf",
        "otf",
        "woff",
        "woff2",
        "eot",
        "db",
        "sqlite",
        "sqlite3",
        "parquet",
        "npy",
        "npz",
        "pt",
        "pth",
        "onnx",
        "safetensors",
        "h5",
        "pkl",
        "lock",
        "map",
        "lnk",
        "dat",
        "snap",
    }
)

# Generated files that are never worth analysing.
GENERATED_FILENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "poetry.lock",
        "pipfile.lock",
        "uv.lock",
        "pdm.lock",
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
        "packages.lock.json",
        "go.sum",
        "gradle.lockfile",
    }
)


def basename(rel: str) -> str:
    """Lower-cased final path component, handling Windows separators."""
    normalized = rel.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1].lower()


def extension(rel: str) -> str:
    base = basename(rel)
    dot = base.rfind(".")
    if dot <= 0:
        return ""
    return base[dot + 1 :]


def has_binary_extension(rel: str) -> bool:
    return extension(rel) in BINARY_EXTENSIONS


def is_generated(rel: str) -> bool:
    return basename(rel) in GENERATED_FILENAMES


def language_of(rel: str) -> Language | None:
    """Classification for a path, or ``None`` when the file type is unknown."""
    base = basename(rel)
    special = SPECIAL_FILENAMES.get(base)
    if special is not None:
        return _BY_NAME.get(special)

    ext = extension(base)
    if ext == "":
        return None
    return _BY_EXTENSION.get(ext)


def is_code(rel: str) -> bool:
    language = language_of(rel)
    return language is not None and language.kind == CODE


def extension_map() -> dict[str, str]:
    """Extension -> language name.

    Exposed so the test suite can assert that every advertised extension really
    resolves. One missing comma turns ``("toml")`` into a plain string, so
    ``for ext in ...`` registers ``t``, ``o``, ``m`` and ``l`` instead of
    ``toml`` — a silent data bug that removed every TOML file from the language
    statistics while still looking correct in review.
    """
    return {ext: language.name for ext, language in _BY_EXTENSION.items()}


def all_language_names() -> list[str]:
    return sorted(_BY_NAME)
