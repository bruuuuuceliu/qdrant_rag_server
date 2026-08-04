"""Structured logging and correlation-ID tests."""

from __future__ import annotations

import json
import logging

from shared.logging import (
    JsonFormatter,
    TextCorrelationFormatter,
    correlation_id,
    get_correlation_id,
)


def _record(message: str, **kwargs: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
        **kwargs,
    )


def test_correlation_id_defaults_empty() -> None:
    assert get_correlation_id() == ""


def test_correlation_id_context_sets_and_restores() -> None:
    with correlation_id("corr-123"):
        assert get_correlation_id() == "corr-123"
    assert get_correlation_id() == ""


def test_json_formatter_includes_correlation_id() -> None:
    formatter = JsonFormatter()
    with correlation_id("corr-456"):
        line = formatter.format(_record("hello"))
    payload = json.loads(line)
    assert payload["correlation_id"] == "corr-456"
    assert payload["msg"] == "hello"
    assert payload["logger"] == "test.logger"
    assert "level" in payload and "ts" in payload


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JsonFormatter()
    record = _record("task event")
    record.task_id = "task-1"  # type: ignore[attr-defined]
    line = formatter.format(record)
    payload = json.loads(line)
    assert payload["task_id"] == "task-1"


def test_json_formatter_without_correlation_id() -> None:
    formatter = JsonFormatter()
    line = formatter.format(_record("plain"))
    payload = json.loads(line)
    assert "correlation_id" not in payload


def test_text_formatter_appends_correlation_id() -> None:
    formatter = TextCorrelationFormatter()
    with correlation_id("corr-789"):
        line = formatter.format(_record("plain text"))
    assert "correlation_id=corr-789" in line
    assert "plain text" in line
