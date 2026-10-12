"""Diagnostics must never reach stdout, and must be quiet by default."""

from __future__ import annotations

import pytest

from codebase_insight import logger


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CBI_DEBUG", raising=False)


def test_debug_is_silent_unless_cbi_debug_is_set(capsys: pytest.CaptureFixture[str]) -> None:
    logger.debug("hidden")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on "])
def test_debug_is_enabled_by_common_truthy_values(
    value: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CBI_DEBUG", value)
    logger.debug("visible")
    assert "visible" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_debug_stays_off_for_falsy_values(
    value: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CBI_DEBUG", value)
    logger.debug("hidden")
    assert capsys.readouterr().err == ""


def test_warn_is_always_emitted(capsys: pytest.CaptureFixture[str]) -> None:
    logger.warn("degraded path")
    assert "degraded path" in capsys.readouterr().err


def test_never_writes_to_stdout(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """stdout is the JSON-RPC channel; a stray write there breaks the session."""
    monkeypatch.setenv("CBI_DEBUG", "1")
    logger.debug("diagnostic")
    logger.warn("warning")
    assert capsys.readouterr().out == ""


def test_formats_non_string_arguments(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CBI_DEBUG", "1")

    class Unserialisable:
        def __repr__(self) -> str:
            return "<unserialisable>"

    logger.debug("nested", {"count": 3}, [1, 2], Unserialisable(), ValueError("boom"))
    err = capsys.readouterr().err

    assert '{"count": 3}' in err
    assert "[1, 2]" in err
    assert "unserialisable" in err
    assert "ValueError: boom" in err
    assert err.startswith(logger.PREFIX)


def test_survives_a_closed_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken pipe must not take the server down with it."""
    monkeypatch.setenv("CBI_DEBUG", "1")

    class BrokenStream:
        def write(self, _: str) -> int:
            raise OSError("pipe closed")

        def flush(self) -> None:
            raise OSError("pipe closed")

    monkeypatch.setattr(logger.sys, "stderr", BrokenStream())
    logger.debug("this must not raise")
    logger.warn("this must not raise either")
