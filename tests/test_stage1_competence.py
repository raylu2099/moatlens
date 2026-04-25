"""
Numerical regression tests for Stage 1 pure-compute helpers.

Covers _compute_roic (5Y ROIC series) and _altman_z (bankruptcy-risk
composite). Both feed the "垃圾桶测试" verdict — getting them wrong
silently lets weak businesses pass the first screen.

This file closes the round-3 audit gap "no dedicated test for s1".
"""

from __future__ import annotations

import pytest

from engine.stages.s1_competence import _altman_z, _compute_roic

# =========================================================================
# _compute_roic — ROIC % per year series
# =========================================================================


def test_roic_basic_single_year():
    """NOPAT = EBIT × (1 - Tc), invested = debt + equity - cash.
    Example: EBIT 100, tax 21, equity 500, debt 0, cash 0
      → NOPAT = 100 × (1 - 0.21) = 79 → ROIC = 79/500 = 15.8%"""
    income = [{"operating_income": 100, "income_tax_expense": 21, "ebit": 100}]
    balance = [{"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 0}]
    series = _compute_roic(income, balance)
    assert len(series) == 1
    assert series[0] == pytest.approx(15.8, abs=0.1)


def test_roic_cash_reduces_invested_capital():
    """Cash-rich balance sheet → lower invested capital → higher ROIC.
    Buffett loves this for exactly this reason."""
    income = [{"operating_income": 100, "income_tax_expense": 21, "ebit": 100}]
    bal_nocash = [{"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 0}]
    bal_cash = [{"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 200}]
    low = _compute_roic(income, bal_nocash)[0]
    high = _compute_roic(income, bal_cash)[0]
    assert high > low


def test_roic_skips_period_with_zero_invested_capital():
    """If debt + equity − cash ≤ 0 (distressed / recently recapped firm),
    skip that period rather than divide by zero."""
    income = [{"operating_income": 100, "income_tax_expense": 21, "ebit": 100}]
    balance = [{"total_debt": 0, "shareholders_equity": 0, "cash_and_equivalents": 0}]
    assert _compute_roic(income, balance) == []


def test_roic_skips_period_with_missing_ebit():
    """No EBIT → can't compute NOPAT. Skip rather than guess."""
    income = [{"operating_income": None, "ebit": None, "income_tax_expense": 10}]
    balance = [{"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 0}]
    assert _compute_roic(income, balance) == []


def test_roic_uses_fallback_tax_rate_when_pretax_negative():
    """Loss year (EBIT < 0) → tax_rate falls back to 0.21 (US statutory)
    rather than producing nonsense from `tax / negative_pretax`. Negative
    NOPAT propagates and ROIC goes negative — that's the correct signal."""
    income = [{"operating_income": -50, "income_tax_expense": 0, "ebit": -50}]
    balance = [{"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 0}]
    series = _compute_roic(income, balance)
    # EBIT -50, fallback tax_rate 0.21 → NOPAT -50 × 0.79 = -39.5
    # invested = 500 → ROIC = -39.5/500 × 100 = -7.9%
    assert series[0] == pytest.approx(-7.9, abs=0.1)


def test_roic_multi_year_preserves_order():
    """Input lists are newest-first (that's the convention in the fd provider).
    Output series stays newest-first so callers can slice [:5] for 5Y average."""
    income = [
        {"operating_income": 100, "income_tax_expense": 21, "ebit": 100},
        {"operating_income": 80, "income_tax_expense": 16, "ebit": 80},
        {"operating_income": 60, "income_tax_expense": 12, "ebit": 60},
    ]
    balance = [
        {"total_debt": 0, "shareholders_equity": 500, "cash_and_equivalents": 0},
    ] * 3
    series = _compute_roic(income, balance)
    assert len(series) == 3
    # Newest (100) should give highest ROIC
    assert series[0] > series[1] > series[2]


# =========================================================================
# _altman_z — bankruptcy-risk composite
# =========================================================================
# Formula: 1.2 × (WC/TA) + 1.4 × (RE/TA) + 3.3 × (EBIT/TA) + 0.6 × (MC/TL) + 1.0 × (Rev/TA)
# Healthy firm: z > 2.99. Gray zone: 1.81-2.99. Distress: < 1.81.


def test_altman_z_healthy_company():
    """Profitable, low leverage, large retained earnings → z > 3."""
    income = {"operating_income": 200, "revenue": 1000, "ebit": 200}
    balance = {
        "total_assets": 1000,
        "total_liabilities": 300,
        "retained_earnings": 500,
        "current_assets": 400,
        "current_liabilities": 100,
    }
    z = _altman_z(income, balance, market_cap=800)
    assert z is not None
    assert z > 3.0


def test_altman_z_distressed_company():
    """Negative EBIT + near-zero retained earnings + high leverage → z < 1.81."""
    income = {"operating_income": -50, "revenue": 500, "ebit": -50}
    balance = {
        "total_assets": 1000,
        "total_liabilities": 900,
        "retained_earnings": 10,
        "current_assets": 100,
        "current_liabilities": 300,  # negative WC
    }
    z = _altman_z(income, balance, market_cap=50)
    assert z is not None
    assert z < 1.81


def test_altman_z_missing_market_cap_returns_none():
    """Without market cap we can't compute the equity-over-liabilities term —
    better to return None than a silently truncated 4-factor score."""
    income = {"operating_income": 100, "revenue": 500, "ebit": 100}
    balance = {
        "total_assets": 1000,
        "total_liabilities": 300,
        "retained_earnings": 100,
        "current_assets": 200,
        "current_liabilities": 100,
    }
    assert _altman_z(income, balance, market_cap=None) is None


def test_altman_z_zero_total_assets_returns_none():
    """Divide-by-zero guard. A firm with TA=0 is either a data error or a
    shell — either way, z-score is meaningless."""
    income = {"operating_income": 100, "revenue": 500}
    balance = {"total_assets": 0, "total_liabilities": 0}
    assert _altman_z(income, balance, market_cap=100) is None


# =========================================================================
# R3-7: ETF / fund / index gate at top of run()
# =========================================================================


def test_run_refuses_etf_quote_type(monkeypatch):
    """ETFs are baskets, not businesses — moat / DCF is meaningless on
    aggregated metrics. The gate must return FAIL before any data fetch."""
    from pathlib import Path

    from engine.stages import s1_competence
    from shared.config import ApiKeys, Config

    monkeypatch.setattr(
        s1_competence.yfp,
        "fetch_company_info",
        lambda t: {"long_name": "SPDR S&P 500", "quote_type": "ETF"},
    )

    cfg = Config(
        data_dir=Path("/tmp"),
        cache_dir=Path("/tmp"),
        prompts_dir=Path("/tmp"),
        docs_dir=Path("/tmp"),
        claude_model="haiku",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60,
        cache_perplexity_ttl=60,
        cache_macro_ttl=60,
        project_root=Path("/tmp"),
    )
    result = s1_competence.run(cfg, ApiKeys(), "SPY")
    from engine.models import Verdict

    assert result.verdict == Verdict.FAIL
    assert "ETF" in result.findings[0]
    assert result.raw_data["quote_type"] == "ETF"


def test_run_refuses_mutual_fund(monkeypatch):
    """Same gate covers MUTUALFUND and INDEX."""
    from pathlib import Path

    from engine.stages import s1_competence
    from shared.config import ApiKeys, Config

    monkeypatch.setattr(
        s1_competence.yfp,
        "fetch_company_info",
        lambda t: {"long_name": "Some Fund", "quote_type": "MUTUALFUND"},
    )

    cfg = Config(
        data_dir=Path("/tmp"),
        cache_dir=Path("/tmp"),
        prompts_dir=Path("/tmp"),
        docs_dir=Path("/tmp"),
        claude_model="haiku",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60,
        cache_perplexity_ttl=60,
        cache_macro_ttl=60,
        project_root=Path("/tmp"),
    )
    result = s1_competence.run(cfg, ApiKeys(), "VTSAX")
    from engine.models import Verdict

    assert result.verdict == Verdict.FAIL


def test_altman_z_handles_missing_total_liabilities():
    """Some balance sheets (pre-IPO / fund) lack `total_liabilities`. The
    equity/liabilities term should degrade to 0 rather than raise."""
    income = {"operating_income": 100, "revenue": 500, "ebit": 100}
    balance = {
        "total_assets": 1000,
        "total_liabilities": None,
        "retained_earnings": 100,
        "current_assets": 300,
        "current_liabilities": 100,
    }
    z = _altman_z(income, balance, market_cap=500)
    # Should compute with d=0 term; result is still a finite number
    assert z is not None
    assert z > 0  # other positive terms dominate
