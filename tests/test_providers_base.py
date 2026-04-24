"""
Regression tests for engine/providers/base.py helpers.

These helpers are consumed by 4 v0.6 providers (sec_api, finnhub, marketaux,
fda) so a silent behavior change ripples across the entire v0.6 enrichment
layer.
"""

from __future__ import annotations

import pytest

from engine.providers.base import (
    cached_call,
    rate_limit_gate,
    stable_cache_key,
)


class DummyError(RuntimeError):
    pass


# -------------------------------------------------------------------------
# rate_limit_gate
# -------------------------------------------------------------------------


def test_rate_limit_gate_wraps_exceeded_as_provider_error(monkeypatch):
    """If require_token raises, rate_limit_gate must re-raise as `error_class`
    so each provider's public API stays homogeneous."""

    def _fake_require(_name):
        raise RuntimeError("bucket empty")

    import shared.ratelimit as rl

    monkeypatch.setattr(rl, "require_token", _fake_require)

    with pytest.raises(DummyError) as ei:
        rate_limit_gate("finnhub", DummyError)
    assert "rate-limit" in str(ei.value)


def test_rate_limit_gate_happy_path_returns_none(monkeypatch):
    """Normal case: no exception → helper returns None silently."""
    import shared.ratelimit as rl

    monkeypatch.setattr(rl, "require_token", lambda _name: None)
    assert rate_limit_gate("finnhub", DummyError) is None


# -------------------------------------------------------------------------
# cached_call
# -------------------------------------------------------------------------


def test_cached_call_miss_then_hit(tmp_path, monkeypatch):
    """First call runs fetcher; second call returns cached value without
    calling fetcher again."""
    from shared.config import Config

    cfg = Config(
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        prompts_dir=tmp_path,
        docs_dir=tmp_path,
        claude_model="x",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=3600,
        cache_perplexity_ttl=3600,
        cache_macro_ttl=3600,
        project_root=tmp_path,
    )
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)

    call_count = {"n": 0}

    def fetcher():
        call_count["n"] += 1
        return {"result": "ok", "n": call_count["n"]}

    v1 = cached_call(cfg, "test_ns", "k1", ttl=3600, fetcher=fetcher)
    v2 = cached_call(cfg, "test_ns", "k1", ttl=3600, fetcher=fetcher)

    assert v1 == v2
    assert call_count["n"] == 1  # fetcher only invoked on the miss


# -------------------------------------------------------------------------
# stable_cache_key
# -------------------------------------------------------------------------


def test_stable_cache_key_is_order_independent_for_dicts():
    """Two providers caching the same params under different dict-iteration
    orders must collide on the same cache file. Prevents drift."""
    k1 = stable_cache_key("path", {"a": 1, "b": 2})
    k2 = stable_cache_key("path", {"b": 2, "a": 1})
    assert k1 == k2


def test_stable_cache_key_differs_on_different_values():
    k1 = stable_cache_key("path", {"a": 1, "b": 2})
    k2 = stable_cache_key("path", {"a": 1, "b": 3})
    assert k1 != k2
