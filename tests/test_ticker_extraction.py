"""Ticker extraction from free-text chat input."""
from __future__ import annotations

import pytest

from web.main import _extract_ticker


@pytest.mark.parametrize("text,expected", [
    # Direct
    ("AAPL", "AAPL"),
    ("aapl", "AAPL"),
    ("BRK.B", "BRK.B"),

    # Natural Chinese + ticker
    ("审视 AAPL", "AAPL"),
    ("我想看 NVDA", "NVDA"),
    ("AAPL 值得买吗？", "AAPL"),
    ("看看 TSLA", "TSLA"),
    ("MSFT 的护城河如何？", "MSFT"),

    # Mixed English + uppercase ticker
    ("should I buy NVDA now", "NVDA"),

    # Lowercase-only fallback (common ticker length)
    ("aapl", "AAPL"),

    # No ticker at all — must NOT fabricate one
    ("this has no ticker at all", None),
    ("how are you today", None),
    ("我不知道", None),
    ("", None),
    ("    ", None),
    ("yes no maybe", None),

    # Stop-words must not be treated as tickers
    ("I want to BUY now", None),
    ("should I HOLD or SELL", None),
    ("CEO 说的话", None),
])
def test_extract_ticker(text, expected):
    assert _extract_ticker(text) == expected


def test_prefers_all_caps_over_lowercase():
    """If user types a clearly-uppercase ticker mixed in, pick that one."""
    assert _extract_ticker("look at AAPL not apple") == "AAPL"
