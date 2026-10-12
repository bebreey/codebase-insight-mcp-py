"""Generated file that .gitignore excludes.

The analyser must never report this file, its symbols or its size. The test
suite asserts exactly that, which is how the pathspec integration is verified.
"""

GENERATED_MARKER = "this file must not be analysed"


def generated_function() -> str:
    return GENERATED_MARKER
