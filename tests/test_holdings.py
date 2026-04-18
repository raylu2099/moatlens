"""Holdings persistence + CRUD tests."""
from __future__ import annotations

import pytest

from shared.config import Config
from shared.holdings import (
    add_holding, holdings_path, is_holding, load_holdings, remove_holding,
)


@pytest.fixture
def cfg(tmp_path) -> Config:
    data = tmp_path / "data"
    data.mkdir()
    return Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


def test_empty_state(cfg):
    assert load_holdings(cfg) == []
    assert is_holding(cfg, "AAPL") is False


def test_add_new_holding(cfg):
    h = add_holding(cfg, "AAPL", size="5%", note="core")
    assert h["ticker"] == "AAPL"
    assert h["size"] == "5%"
    assert h["note"] == "core"
    assert "added_at" in h

    all_ = load_holdings(cfg)
    assert len(all_) == 1
    assert all_[0]["ticker"] == "AAPL"


def test_add_upserts_existing_ticker(cfg):
    add_holding(cfg, "AAPL", size="5%", note="first")
    add_holding(cfg, "AAPL", size="10%", note="doubled down")
    all_ = load_holdings(cfg)
    assert len(all_) == 1
    assert all_[0]["size"] == "10%"
    assert all_[0]["note"] == "doubled down"
    assert all_[0]["updated_at"]  # set on upsert


def test_ticker_is_upper_cased(cfg):
    add_holding(cfg, "aapl", size="5%")
    assert is_holding(cfg, "aapl") is True
    assert is_holding(cfg, "AAPL") is True


def test_remove_holding(cfg):
    add_holding(cfg, "AAPL")
    add_holding(cfg, "NVDA")
    assert remove_holding(cfg, "AAPL") is True
    remaining = load_holdings(cfg)
    assert [h["ticker"] for h in remaining] == ["NVDA"]


def test_remove_nonexistent_returns_false(cfg):
    assert remove_holding(cfg, "NOPE") is False


def test_atomic_write_leaves_no_tmp_file_after_success(cfg):
    add_holding(cfg, "AAPL")
    p = holdings_path(cfg)
    tmp = p.with_suffix(p.suffix + ".tmp")
    assert p.exists()
    assert not tmp.exists()


def test_load_tolerates_corrupt_file(cfg):
    """If holdings.json is manually edited into garbage, we return [] (not crash)."""
    p = holdings_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {{{", encoding="utf-8")
    assert load_holdings(cfg) == []
