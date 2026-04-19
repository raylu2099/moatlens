"""Metrics logging tests — no network, pure filesystem."""
from __future__ import annotations

import json

import pytest

from shared.config import Config
from shared.metrics import cost_log_path, log_cost, read_cost_entries, total_cost


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path / "data", cache_dir=tmp_path / "data" / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="", pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


def test_log_cost_appends_jsonl(cfg):
    log_cost(cfg, provider="claude", cost_usd=0.05, model="claude-sonnet-4-5",
             input_tok=1000, output_tok=500, stage=3, tag="audit")
    log_cost(cfg, provider="perplexity", cost_usd=0.01, tag="s3_research")

    entries = read_cost_entries(cfg)
    assert len(entries) == 2
    assert entries[0]["provider"] == "claude"
    assert entries[0]["cost_usd"] == 0.05
    assert entries[1]["provider"] == "perplexity"


def test_log_cost_creates_dir_if_absent(cfg):
    # metrics/ shouldn't exist yet; log_cost must mkdir -p
    log_cost(cfg, provider="claude", cost_usd=0.01)
    assert cost_log_path(cfg).exists()
    assert cost_log_path(cfg).parent.name == "metrics"


def test_log_cost_swallows_errors(monkeypatch, cfg):
    """A bug in the logger must never break a live audit."""
    def boom(*args, **kwargs):
        raise RuntimeError("simulated disk full")
    monkeypatch.setattr("shared.metrics.cost_log_path", boom)
    # Should return without raising
    log_cost(cfg, provider="claude", cost_usd=0.01)


def test_total_cost_aggregates(cfg):
    for c in [0.10, 0.05, 0.20]:
        log_cost(cfg, provider="claude", cost_usd=c)
    assert total_cost(cfg) == pytest.approx(0.35)


def test_total_cost_since_filters(cfg):
    # Oldest first
    log_cost(cfg, provider="claude", cost_usd=0.10)
    # Manually write an old entry
    p = cost_log_path(cfg)
    with p.open("a") as f:
        f.write(json.dumps({"ts": "2020-01-01T00:00:00+00:00", "cost_usd": 1.00}) + "\n")
    total_since = total_cost(cfg, since_iso="2025-01-01")
    assert total_since == pytest.approx(0.10)
