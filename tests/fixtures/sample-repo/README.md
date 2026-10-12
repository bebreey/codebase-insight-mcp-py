# sample-repo

A fixture repository used as analysis input by the `codebase-insight-mcp-py`
test suite. Nothing here is meant to run in production.

## Layout

- `src/sample/calculator.py` — class, methods, a nested function, module constants,
  and three debt markers
- `src/sample/config.py` — one entirely fake credential-shaped literal
- `src/sample/generated/` — excluded by `.gitignore`, must never be analysed
- `tests/test_calculator.py` — makes the fixture look like a tested project
- `docs/notes.md` — a Markdown task list, to exercise the prose marker path

## Usage

```bash
pytest
```
