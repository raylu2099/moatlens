"""v0.6 enrichment helper tests — monkeypatch providers, no network."""

from __future__ import annotations

import pytest

from engine.stages import _enrichments as enr
from shared.config import ApiKeys, Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        prompts_dir=tmp_path / "prompts",
        docs_dir=tmp_path / "docs",
        claude_model="",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60,
        cache_perplexity_ttl=60,
        cache_macro_ttl=60,
        project_root=tmp_path,
    )


def test_sec_mda_returns_none_when_key_missing(cfg):
    keys = ApiKeys()  # no sec_api_io
    assert enr.sec_mda_excerpt(cfg, keys, "AAPL") is None


def test_sec_mda_returns_none_on_provider_error(cfg, monkeypatch):
    keys = ApiKeys(sec_api_io="dummy")

    def boom(*_a, **_kw):
        raise RuntimeError("network fail")

    from engine.providers import sec_api

    monkeypatch.setattr(sec_api, "fetch_mda", boom)
    assert enr.sec_mda_excerpt(cfg, keys, "AAPL") is None


def test_sec_mda_returns_formatted_finding(cfg, monkeypatch):
    keys = ApiKeys(sec_api_io="dummy")
    long_text = "Item 7 discussion of results. " * 50

    from engine.providers import sec_api

    monkeypatch.setattr(sec_api, "fetch_mda", lambda *a, **kw: long_text)
    out = enr.sec_mda_excerpt(cfg, keys, "AAPL", max_chars=100)
    assert out is not None
    assert "SEC MD&A" in out
    assert len(out) < 500


def test_finnhub_insider_summary_no_key(cfg):
    keys = ApiKeys()
    line, raw = enr.finnhub_insider_summary(cfg, keys, "AAPL")
    assert line is None
    assert raw is None


def test_finnhub_insider_summary_normal(cfg, monkeypatch):
    keys = ApiKeys(finnhub="dummy")
    from engine.providers import finnhub

    monkeypatch.setattr(
        finnhub,
        "fetch_insider_transactions",
        lambda *a, **kw: {
            "tx_count": 12,
            "net_shares": -50000,
            "net_dollars": -8_500_000.0,
            "rows": [],
            "window_days": 180,
        },
    )
    line, raw = enr.finnhub_insider_summary(cfg, keys, "AAPL")
    assert line is not None
    assert "净卖出" in line
    assert "180 天" in line
    assert raw["tx_count"] == 12


def test_finnhub_consensus_summary_labels(cfg, monkeypatch):
    keys = ApiKeys(finnhub="dummy")
    from engine.providers import finnhub

    monkeypatch.setattr(
        finnhub,
        "fetch_recommendation_trends",
        lambda *a, **kw: [
            {
                "period": "2026-04-01",
                "strongBuy": 20,
                "buy": 10,
                "hold": 5,
                "sell": 2,
                "strongSell": 1,
            }
        ],
    )
    # Use real summarize_consensus
    line, raw = enr.finnhub_consensus_summary(cfg, keys, "NVDA")
    assert line is not None
    assert raw["label"] in ("overwhelmingly_bullish", "bullish")


def test_finnhub_consensus_returns_none_when_no_analysts(cfg, monkeypatch):
    keys = ApiKeys(finnhub="dummy")
    from engine.providers import finnhub

    monkeypatch.setattr(finnhub, "fetch_recommendation_trends", lambda *a, **kw: [])
    line, raw = enr.finnhub_consensus_summary(cfg, keys, "UNKNOWN")
    assert line is None


def test_marketaux_sentiment_label_thresholds():
    from engine.providers.marketaux import sentiment_label

    assert sentiment_label(0.5, 10) == "strongly_positive"
    assert sentiment_label(0.1, 10) == "mildly_positive"
    assert sentiment_label(0.0, 10) == "neutral"
    assert sentiment_label(-0.1, 10) == "mildly_negative"
    assert sentiment_label(-0.5, 10) == "strongly_negative"
    # n/a when too few
    assert sentiment_label(0.5, 2) == "n/a"


def test_marketaux_enrichment_none_when_no_articles(cfg, monkeypatch):
    keys = ApiKeys(marketaux="dummy")
    from engine.providers import marketaux

    monkeypatch.setattr(
        marketaux,
        "fetch_news_sentiment",
        lambda *a, **kw: {
            "avg_sentiment": 0.0,
            "article_count": 0,
            "positive_pct": 0.0,
            "negative_pct": 0.0,
            "top_headlines": [],
            "window_days": 30,
        },
    )
    line, raw = enr.marketaux_sentiment_summary(cfg, keys, "XYZ")
    assert line is None


def test_fda_pipeline_gated_by_sector(cfg):
    keys = ApiKeys()
    # Non-health sector → None without touching provider
    line, raw = enr.fda_pipeline_summary(cfg, keys, "Apple", sector="Technology")
    assert line is None
    assert raw is None


def test_fda_pipeline_runs_for_healthcare(cfg, monkeypatch):
    keys = ApiKeys()
    from engine.providers import fda

    monkeypatch.setattr(
        fda,
        "pipeline_summary",
        lambda *a, **kw: {
            "company": "Novo Nordisk",
            "pipeline_strength": "deep",
            "active_phase_3": 8,
            "active_phase_2": 15,
            "active_phase_1": 20,
            "total_active_trials": 43,
            "approvals_last_5y": 6,
            "approved_products": [],
        },
    )
    line, raw = enr.fda_pipeline_summary(cfg, keys, "Novo Nordisk", sector="Healthcare")
    assert line is not None
    assert "深厚" in line
    assert raw["active_phase_3"] == 8


def test_fda_pipeline_dry_appends_red_flag(cfg, monkeypatch):
    keys = ApiKeys()
    from engine.providers import fda

    monkeypatch.setattr(
        fda,
        "pipeline_summary",
        lambda *a, **kw: {
            "company": "OldPharma",
            "pipeline_strength": "dry",
            "active_phase_3": 0,
            "active_phase_2": 0,
            "active_phase_1": 0,
            "total_active_trials": 0,
            "approvals_last_5y": 0,
            "approved_products": [],
        },
    )
    line, _ = enr.fda_pipeline_summary(cfg, keys, "OldPharma", sector="Healthcare")
    assert line is not None
    assert "红旗" in line
