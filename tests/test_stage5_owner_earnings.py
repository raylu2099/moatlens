"""
Numerical regression tests for Stage 5 pure compute functions.

These are the highest-stakes calcs in the project — a wrong owner-earnings
formula directly distorts the buy/sell price. Every change to
`engine/stages/s5_owner_earnings.py` MUST keep these passing.
"""

from __future__ import annotations

import pytest

from engine.stages.s5_owner_earnings import (
    _compute_owner_earnings,
    _dupont,
    _effective_tax_rate_from_income,
    _is_high_capex,
)

# =========================================================================
# Owner earnings
# =========================================================================


def test_owner_earnings_basic_without_sbc():
    """
    Buffett approximation: OE = NI + DA - maint_capex.
    When capex > DA, maint_capex = min(capex, DA) = DA.
    """
    income = {"net_income": 100, "depreciation_and_amortization": 50}
    cashflow = {"capital_expenditure": -60, "share_based_compensation": 10}
    oe, detail = _compute_owner_earnings(income, cashflow, subtract_sbc=False)

    # NI=100, DA=50, maint_capex = min(60, 50) = 50, SBC ignored
    assert oe == pytest.approx(100.0)
    assert detail["maintenance_capex_proxy"] == 50
    assert detail["sbc_subtracted"] is False


def test_owner_earnings_tech_mode_subtracts_sbc():
    """Tech mode: OE also subtracts Stock-Based Compensation (Buffett 2019 letter)."""
    income = {"net_income": 100, "depreciation_and_amortization": 50}
    cashflow = {"capital_expenditure": -60, "share_based_compensation": 20}
    oe, detail = _compute_owner_earnings(income, cashflow, subtract_sbc=True)

    assert oe == pytest.approx(80.0)  # 100 + 50 - 50 - 20
    assert detail["sbc_subtracted"] is True


def test_owner_earnings_capex_below_da():
    """When capex < DA, maint_capex = capex (we don't overstate deterioration)."""
    income = {"net_income": 100, "depreciation_and_amortization": 80}
    cashflow = {"capital_expenditure": -30}
    oe, detail = _compute_owner_earnings(income, cashflow, subtract_sbc=False)

    # NI=100, DA=80, maint=min(30, 80)=30 → OE = 100 + 80 - 30 = 150
    assert oe == pytest.approx(150.0)
    assert detail["maintenance_capex_proxy"] == 30


def test_owner_earnings_zero_da_falls_back_to_fraction_of_capex():
    """When DA is absent, use 70% of capex as maintenance proxy (conservative)."""
    income = {"net_income": 100, "depreciation_and_amortization": 0}
    cashflow = {"capital_expenditure": -100}
    oe, detail = _compute_owner_earnings(income, cashflow, subtract_sbc=False)

    # NI=100, DA=0, maint = 100 * 0.7 = 70 → OE = 100 + 0 - 70 = 30
    assert oe == pytest.approx(30.0)
    assert detail["maintenance_capex_proxy"] == pytest.approx(70.0)


def test_owner_earnings_handles_missing_fields():
    """Missing fields default to 0 — no KeyError, no NoneType math."""
    oe, _ = _compute_owner_earnings({}, {}, subtract_sbc=True)
    assert oe == 0


def test_owner_earnings_negative_net_income():
    """Loss-making companies: OE can go negative, and that's informative."""
    income = {"net_income": -50, "depreciation_and_amortization": 20}
    cashflow = {"capital_expenditure": -100, "share_based_compensation": 30}
    oe, _ = _compute_owner_earnings(income, cashflow, subtract_sbc=True)
    # NI=-50, DA=20, maint=min(100, 20)=20, SBC=30 → -50 + 20 - 20 - 30 = -80
    assert oe == pytest.approx(-80.0)


def test_owner_earnings_capex_sign_tolerant():
    """capex may arrive as negative (cashflow out) or positive — we take abs()."""
    income = {"net_income": 100, "depreciation_and_amortization": 40}
    neg_sign = {"capital_expenditure": -50}
    pos_sign = {"capital_expenditure": 50}
    oe_neg, _ = _compute_owner_earnings(income, neg_sign, subtract_sbc=False)
    oe_pos, _ = _compute_owner_earnings(income, pos_sign, subtract_sbc=False)
    assert oe_neg == oe_pos


# =========================================================================
# DuPont
# =========================================================================


def test_dupont_basic():
    """
    Net margin × Asset turnover × Leverage ≈ ROE.
    NM = NI/Rev, AT = Rev/TA, Lev = TA/Equity → product = NI/Equity = ROE.
    """
    income = {"net_income": 100, "revenue": 1000}
    balance = {"total_assets": 500, "shareholders_equity": 200}
    d = _dupont(income, balance)

    assert d["net_margin_pct"] == pytest.approx(10.0)
    assert d["asset_turnover"] == pytest.approx(2.0)
    assert d["leverage"] == pytest.approx(2.5)
    # ROE = 10% × 2 × 2.5 = 50% — check via the function's own output
    assert d["roe_pct"] == pytest.approx(50.0)


def test_dupont_identity_holds_numerically():
    """ROE from DuPont must equal NI/Equity × 100."""
    income = {"net_income": 75, "revenue": 800}
    balance = {"total_assets": 400, "shareholders_equity": 150}
    d = _dupont(income, balance)
    direct_roe = 75 / 150 * 100
    assert d["roe_pct"] == pytest.approx(direct_roe)


def test_dupont_handles_zero_denominators():
    """Division-by-zero protection: treats missing denominators as 1 (sentinel)."""
    d = _dupont({"net_income": 0, "revenue": 0}, {"total_assets": 0, "shareholders_equity": 0})
    # With the current sentinel (denominators default to 1), everything collapses to 0.
    assert d["net_margin_pct"] == 0
    assert d["roe_pct"] == 0


# =========================================================================
# v0.6.1: DuPont with average assets (P1-2)
# =========================================================================


def test_dupont_without_balance_prev_uses_end_of_period():
    """Legacy callers that don't pass balance_prev get the old single-period
    behavior — this is what preserves all the pre-v0.6.1 numerical tests."""
    income = {"net_income": 100, "revenue": 1000}
    balance = {"total_assets": 500, "shareholders_equity": 200}
    d = _dupont(income, balance)
    assert d["used_average_assets"] is False
    assert d["asset_turnover"] == pytest.approx(2.0)
    assert d["leverage"] == pytest.approx(2.5)


def test_dupont_with_balance_prev_averages_assets():
    """CFA-canonical denominator: (begin + end)/2. A firm whose assets grew
    from 400 → 500 over the year should get AT ≈ 1000/450 = 2.22, not
    1000/500 = 2.0."""
    income = {"net_income": 100, "revenue": 1000}
    balance_end = {"total_assets": 500, "shareholders_equity": 200}
    balance_begin = {"total_assets": 400, "shareholders_equity": 150}
    d = _dupont(income, balance_end, balance_prev=balance_begin)

    assert d["used_average_assets"] is True
    assert d["asset_turnover"] == pytest.approx(1000 / 450, rel=1e-4)
    assert d["leverage"] == pytest.approx(450 / 175, rel=1e-4)
    # ROE identity still holds on averages: NI / avg_equity
    assert d["roe_pct"] == pytest.approx(100 / 175 * 100, rel=1e-4)


def test_dupont_balance_prev_falls_back_when_field_missing():
    """If balance_prev is partial (missing a field), back-fill from end
    rather than collapsing to the 1-sentinel. Otherwise a rollup that's
    missing historical equity silently tanks the ROE."""
    income = {"net_income": 100, "revenue": 1000}
    balance_end = {"total_assets": 500, "shareholders_equity": 200}
    balance_begin = {"total_assets": 400}  # equity missing
    d = _dupont(income, balance_end, balance_prev=balance_begin)
    # Equity averaged with fallback to ending (200, 200) → avg 200, not 100
    assert d["leverage"] == pytest.approx(450 / 200, rel=1e-4)


# =========================================================================
# v0.6.1: high-capex industry matcher (P0-2)
# =========================================================================


def test_high_capex_sector_matches():
    assert _is_high_capex("Energy", "") is True
    assert _is_high_capex("Utilities", "") is True
    assert _is_high_capex("Basic Materials", "") is True


def test_high_capex_industry_keyword_matches():
    """Semis are Technology-sector but deserve the caveat."""
    assert _is_high_capex("Technology", "Semiconductors") is True
    assert _is_high_capex("Industrials", "Airlines") is True


def test_high_capex_asset_light_sectors_do_not_match():
    """Buffett's approximation is fine for SaaS, consumer packaged goods,
    banking etc. — don't spam the caveat."""
    assert _is_high_capex("Technology", "Software - Application") is False
    assert _is_high_capex("Consumer Defensive", "Beverages - Non-Alcoholic") is False
    assert _is_high_capex("Financial Services", "Credit Services") is False


# =========================================================================
# v0.6.1: effective tax rate helper (P2-2)
# =========================================================================


def test_effective_tax_normal_year():
    r = _effective_tax_rate_from_income({"pretax_income": 100, "income_tax_expense": 21})
    assert r == pytest.approx(0.21)


def test_effective_tax_loss_year_returns_none():
    r = _effective_tax_rate_from_income({"pretax_income": -10, "income_tax_expense": 5})
    assert r is None


def test_effective_tax_outlier_returns_none():
    r = _effective_tax_rate_from_income({"pretax_income": 100, "income_tax_expense": 80})
    assert r is None  # > 35% → likely one-off, fall back to statutory
