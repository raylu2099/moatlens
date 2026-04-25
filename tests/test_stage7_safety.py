"""
Integration-style tests for Stage 7 (safety margin / asymmetry) math.

Tests the `run()` entry point with synthetic stage-6 raw data. The math
that converts DCF scenarios into target buy/sell prices and asymmetry
ratios was previously only validated via a smoke audit — this file locks
the contract with specific numbers.

Note: Kelly fraction tests already live in test_stage6_valuation.py (they
moved there because _kelly_fraction was co-imported for brevity). Kept
there intentionally — this file covers the OUTER math, not Kelly.
"""

from __future__ import annotations

import pytest

from engine.models import Verdict
from engine.stages.s7_safety import run as run_s7
from shared.config import ApiKeys, Config


def _mk_stage6_raw(
    *,
    current_price: float = 100.0,
    bear_iv: float = 60.0,
    base_iv: float = 120.0,
    bull_iv: float = 180.0,
) -> dict:
    """Build a synthetic stage 6 raw_data dict matching ValuationOutput.model_dump."""
    return {
        "valuation": {
            "current_price": current_price,
            "dcf_scenarios": [
                {
                    "label": "bear",
                    "intrinsic_value_per_share": bear_iv,
                    "fcf_growth_rate": 3.0,
                    "terminal_growth": 2.0,
                    "wacc": 11.0,
                },
                {
                    "label": "base",
                    "intrinsic_value_per_share": base_iv,
                    "fcf_growth_rate": 8.0,
                    "terminal_growth": 2.5,
                    "wacc": 10.0,
                },
                {
                    "label": "bull",
                    "intrinsic_value_per_share": bull_iv,
                    "fcf_growth_rate": 15.0,
                    "terminal_growth": 3.0,
                    "wacc": 9.5,
                },
            ],
            "reverse_dcf_implied_growth": 7.5,
            "monte_carlo_p5": 70.0,
            "monte_carlo_p50": 120.0,
            "monte_carlo_p95": 200.0,
        }
    }


# s7.run only reads stage6_raw for math, but its enrichment helpers
# (finnhub_consensus_summary, etc.) check `keys.<provider>` truthiness. Empty
# strings disable all enrichments, leaving math paths under test.
def _StubCfg():
    return Config(
        data_dir=__import__("pathlib").Path("/tmp"),
        cache_dir=__import__("pathlib").Path("/tmp"),
        prompts_dir=__import__("pathlib").Path("/tmp"),
        docs_dir=__import__("pathlib").Path("/tmp"),
        claude_model="claude-haiku-4-5",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=86400,
        cache_perplexity_ttl=86400,
        cache_macro_ttl=86400,
        project_root=__import__("pathlib").Path("/tmp"),
    )


def _StubKeys():
    return ApiKeys()


# =========================================================================
# Target price math — the three trading bands
# =========================================================================


def test_target_buy_is_70pct_of_base_iv():
    """🟢 理想买入 = IV × 0.7 — this is the value-investor margin-of-safety band."""
    r = run_s7(_StubCfg(), _StubKeys(), "X", stage6_raw=_mk_stage6_raw(base_iv=100.0))
    assert r.raw_data["target_buy"] == pytest.approx(70.0)


def test_target_aggressive_is_50pct_of_base_iv():
    """🚀 激进加仓 = IV × 0.5 — the "back up the truck" band."""
    r = run_s7(_StubCfg(), _StubKeys(), "X", stage6_raw=_mk_stage6_raw(base_iv=100.0))
    assert r.raw_data["target_aggressive"] == pytest.approx(50.0)


def test_target_sell_is_110pct_of_base_iv():
    """🔴 开始减仓 = IV × 1.1 — discipline: trim above your best estimate."""
    r = run_s7(_StubCfg(), _StubKeys(), "X", stage6_raw=_mk_stage6_raw(base_iv=100.0))
    assert r.raw_data["target_sell"] == pytest.approx(110.0)


# =========================================================================
# Margin of safety — (base_iv - price) / base_iv × 100
# =========================================================================


def test_mos_pct_undervalued_case():
    """price $70 vs base_iv $100 → MOS 30%."""
    r = run_s7(
        _StubCfg(), _StubKeys(), "X", stage6_raw=_mk_stage6_raw(current_price=70.0, base_iv=100.0)
    )
    assert r.raw_data["margin_of_safety_pct"] == pytest.approx(30.0)


def test_mos_pct_overvalued_case_goes_negative():
    """price $150 vs base_iv $100 → MOS −50% (溢价)."""
    r = run_s7(
        _StubCfg(), _StubKeys(), "X", stage6_raw=_mk_stage6_raw(current_price=150.0, base_iv=100.0)
    )
    assert r.raw_data["margin_of_safety_pct"] == pytest.approx(-50.0)


# =========================================================================
# Asymmetry ratio — upside% / downside%
# =========================================================================


def test_asymmetry_ratio_good_bet():
    """bull $180 / base $100 / bear $60 from price $100:
    upside  = (180−100)/100 = +80%
    downside = (100−60)/100 = +40%
    ratio = 80/40 = 2.0  → a 2:1 good bet."""
    r = run_s7(
        _StubCfg(),
        _StubKeys(),
        "X",
        stage6_raw=_mk_stage6_raw(current_price=100.0, bear_iv=60.0, base_iv=100.0, bull_iv=180.0),
    )
    assert r.raw_data["asymmetry_ratio"] == pytest.approx(2.0, abs=0.01)


def test_asymmetry_ratio_bad_bet():
    """More downside than upside → ratio < 1 → Munger "this is a trap"."""
    r = run_s7(
        _StubCfg(),
        _StubKeys(),
        "X",
        stage6_raw=_mk_stage6_raw(current_price=100.0, bear_iv=40.0, base_iv=100.0, bull_iv=120.0),
    )
    # upside 20% / downside 60% = 0.33
    assert r.raw_data["asymmetry_ratio"] == pytest.approx(0.333, abs=0.01)


# =========================================================================
# Stage-level SKIP paths
# =========================================================================


def test_s7_skips_when_stage6_has_no_scenarios():
    """No stage-6 output → can't compute targets → SKIP loudly, don't pretend."""
    r = run_s7(_StubCfg(), _StubKeys(), "X", stage6_raw={})
    assert r.verdict == Verdict.SKIP


def test_s7_skips_when_base_iv_zero():
    """WACC ≤ terminal growth collapsed base to 0 → skip gracefully; don't
    emit divide-by-zero-shaped garbage."""
    r = run_s7(
        _StubCfg(),
        _StubKeys(),
        "X",
        stage6_raw=_mk_stage6_raw(base_iv=0.0, bear_iv=0.0, bull_iv=0.0),
    )
    assert r.verdict == Verdict.SKIP
