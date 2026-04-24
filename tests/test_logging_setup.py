"""
Regression tests for the secret-redaction filter in JsonFormatter /
ConsoleFormatter (v0.6.1 audit fix P1-6).

Why these exist: the formatter iterates `record.__dict__` and dumps every
non-reserved extra into the log file. Without a name-based blocklist, a
single `logger.info("…", extra={"api_key": key})` landmine would persist
a live Anthropic / Finnhub / MarketAux key into logs/moatlens.log (file
rotates but is world-readable on disk and included in bin/backup.sh).
"""

from __future__ import annotations

import json
import logging

from shared.logging_setup import ConsoleFormatter, JsonFormatter, _is_secret_key


def _make_record(extras: dict) -> logging.LogRecord:
    r = logging.LogRecord(
        name="moatlens.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )
    for k, v in extras.items():
        setattr(r, k, v)
    return r


# -------------------------------------------------------------------------
# _is_secret_key — the matcher
# -------------------------------------------------------------------------


def test_is_secret_key_catches_obvious():
    for name in (
        "api_key",
        "API_KEY",
        "anthropic_key",
        "secret",
        "client_secret",
        "token",
        "bearer_token",
        "access_token",
        "password",
        "passwd",
        "authorization",
        "auth_header",
        "credential",
        "credentials",
        "session_cookie",
    ):
        assert _is_secret_key(name), f"expected secret: {name}"


def test_is_secret_key_leaves_benign_names_alone():
    for name in (
        "ticker",
        "stage",
        "count",
        "elapsed_seconds",
        "verdict",
        "session_id",  # id != secret
        "ratio",
        "price",
        "iv",
    ):
        assert not _is_secret_key(name), f"false positive: {name}"


# -------------------------------------------------------------------------
# JsonFormatter — file log
# -------------------------------------------------------------------------


def test_json_formatter_redacts_secret_extras():
    rec = _make_record(
        {
            "api_key": "sk-proj-super-secret-do-not-leak",
            "finnhub_token": "abc123",
            "ticker": "AAPL",
            "stage": 5,
        }
    )
    out = json.loads(JsonFormatter().format(rec))
    assert out["api_key"] == "[REDACTED]"
    assert out["finnhub_token"] == "[REDACTED]"
    # Benign fields pass through unchanged — redaction must not over-capture.
    assert out["ticker"] == "AAPL"
    assert out["stage"] == 5


def test_json_formatter_preserves_core_fields():
    rec = _make_record({})
    out = json.loads(JsonFormatter().format(rec))
    assert out["level"] == "INFO"
    assert out["logger"] == "moatlens.test"
    assert out["msg"] == "test"
    assert "ts" in out


def test_json_formatter_redaction_covers_nested_like_values():
    """Redaction is by **name**, not value inspection. A dict containing a
    live key under a secret-named attribute is still redacted to a string."""
    rec = _make_record({"anthropic_api_key": {"value": "sk-live-xxx"}})
    out = json.loads(JsonFormatter().format(rec))
    assert out["anthropic_api_key"] == "[REDACTED]"


# -------------------------------------------------------------------------
# ConsoleFormatter — stderr log
# -------------------------------------------------------------------------


def test_console_formatter_redacts_secret_extras():
    rec = _make_record(
        {
            "api_key": "sk-proj-leak",
            "ticker": "NVDA",
        }
    )
    line = ConsoleFormatter().format(rec)
    assert "[REDACTED]" in line
    assert "sk-proj-leak" not in line
    assert "ticker=NVDA" in line
