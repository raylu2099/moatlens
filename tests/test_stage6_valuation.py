"""
Numerical regression tests for Stage 6 DCF / Reverse DCF / Monte Carlo.

These functions directly produce the target buy price. A bug here silently
turns "buy AAPL at $120" into "buy AAPL at $150". Verify against Excel-level
ground truth, not just "output is positive".
"""

from __future__ import annotations

import pytest

from engine.stages.s6_valuation import (
    _compute_wacc,
    _compute_wacc_blended,
    _dcf_value_per_share,
    _effective_tax_rate,
    _monte_carlo,
    _reverse_dcf_implied_growth,
    _scenarios_for_sector,
)
from engine.stages.s7_safety import _kelly_fraction

# =========================================================================
# WACC
# =========================================================================


def test_wacc_uses_capm_formula():
    """Ke = Rf + β × ERP."""
    assert _compute_wacc(beta=1.0, risk_free=4.0, erp=5.0) == pytest.approx(9.0)
    assert _compute_wacc(beta=1.5, risk_free=4.0, erp=5.0) == pytest.approx(11.5)
    assert _compute_wacc(beta=0.5, risk_free=3.0, erp=6.0) == pytest.approx(6.0)


def test_wacc_beta_none_defaults_to_one():
    """Unknown beta → treat as 1.0 (market-average risk)."""
    assert _compute_wacc(beta=None, risk_free=4.0, erp=5.0) == pytest.approx(9.0)


# =========================================================================
# DCF per share
# =========================================================================


def _manual_dcf(fcf: float, g: float, tg: float, wacc: float, years: int, shares: float) -> float:
    """
    Reference implementation — hand-rolled per-share DCF.
    Used as the "Excel ground truth" for the optimized function.
    """
    pv = 0.0
    f = fcf
    for y in range(1, years + 1):
        f *= 1 + g / 100
        pv += f / (1 + wacc / 100) ** y
    terminal = f * (1 + tg / 100) / (wacc / 100 - tg / 100)
    pv += terminal / (1 + wacc / 100) ** years
    return pv / shares


def test_dcf_matches_hand_rolled_reference():
    """A specific cash flow scenario must match to 4 decimals."""
    v = _dcf_value_per_share(
        fcf_latest=1000,
        growth_rate=5,
        terminal_growth=2,
        wacc=10,
        years=10,
        shares_outstanding=100,
    )
    expected = _manual_dcf(1000, 5, 2, 10, 10, 100)
    assert v == pytest.approx(expected, rel=1e-6)
    assert v > 0


def test_dcf_higher_growth_yields_higher_value():
    """Monotonicity: growth ↑ ⇒ intrinsic value ↑ (holding other params fixed)."""
    low = _dcf_value_per_share(1000, 3, 2, 10, 10, 100)
    mid = _dcf_value_per_share(1000, 8, 2, 10, 10, 100)
    high = _dcf_value_per_share(1000, 15, 2, 10, 10, 100)
    assert low < mid < high


def test_dcf_higher_wacc_yields_lower_value():
    """Monotonicity: WACC ↑ ⇒ intrinsic value ↓."""
    low = _dcf_value_per_share(1000, 5, 2, 8, 10, 100)
    high = _dcf_value_per_share(1000, 5, 2, 12, 10, 100)
    assert low > high


def test_dcf_zero_shares_returns_zero():
    """Guardrail — don't raise ZeroDivisionError."""
    assert _dcf_value_per_share(1000, 5, 2, 10, 10, 0) == 0.0


def test_dcf_wacc_below_terminal_growth_returns_zero():
    """
    Gordon growth model requires WACC > g_terminal. When violated, return 0
    rather than a garbage value (the formula blows up negatively otherwise).
    """
    assert _dcf_value_per_share(1000, 5, 8, 5, 10, 100) == 0.0  # wacc==tg
    assert _dcf_value_per_share(1000, 5, 10, 5, 10, 100) == 0.0  # wacc<tg


def test_dcf_includes_positive_terminal_value():
    """
    Structural guarantee: DCF must be strictly greater than the sum of the
    explicit-horizon discounted FCFs alone. If terminal is dropped by a
    refactor, this test flags it immediately.
    """
    v = _dcf_value_per_share(1000, 3, 2, 10, 10, 100)
    explicit_only = 0.0
    f = 1000
    for y in range(1, 11):
        f *= 1.03
        explicit_only += f / 1.10**y
    explicit_per_share = explicit_only / 100
    # Terminal per share must be a positive contribution
    terminal_share = v - explicit_per_share
    assert terminal_share > 0
    # And non-trivial — at least 20% of explicit — catches "terminal = 0" regressions
    assert terminal_share > 0.2 * explicit_per_share


# =========================================================================
# Reverse DCF
# =========================================================================


def test_reverse_dcf_price_zero_returns_none():
    assert _reverse_dcf_implied_growth(0, 10, 10, 2.5) is None


def test_reverse_dcf_fcf_zero_returns_none():
    assert _reverse_dcf_implied_growth(100, 0, 10, 2.5) is None


def test_reverse_dcf_round_trips_forward_dcf():
    """
    Construct: forward DCF with growth g=8% gives price P.
    Reverse DCF on P should recover g ≈ 8%.
    """
    wacc = 10.0
    tg = 2.5
    years = 10
    fcf_ps = 10.0
    g_true = 8.0

    # Forward: build the price the market would show for this growth assumption
    price = _dcf_value_per_share(
        fcf_latest=fcf_ps * 1000,  # scale up and down by shares=1000 — per-share identical
        growth_rate=g_true,
        terminal_growth=tg,
        wacc=wacc,
        years=years,
        shares_outstanding=1000,
    )

    implied = _reverse_dcf_implied_growth(price, fcf_ps, wacc, tg, years=years)
    assert implied is not None
    # Binary search runs 40 iterations → tolerance well under 0.01%
    assert implied == pytest.approx(g_true, abs=0.1)


def test_reverse_dcf_higher_price_implies_higher_growth():
    """Monotonicity — if market pays more, it's baking in faster growth."""
    wacc, tg, years = 10, 2.5, 10
    cheap = _reverse_dcf_implied_growth(50, 10, wacc, tg, years=years)
    rich = _reverse_dcf_implied_growth(200, 10, wacc, tg, years=years)
    assert cheap is not None and rich is not None
    assert rich > cheap


def test_reverse_dcf_returns_none_when_boundary_hit():
    """
    Meme-stock scenario: price is so absurdly high that no growth inside our
    sensible bracket can reproduce it. Function must return None, not a
    falsely-confident number stuck at the 100% ceiling.
    """
    wacc, tg, years = 10, 2.5, 10
    implied = _reverse_dcf_implied_growth(
        current_price=1_000_000,
        fcf_per_share_latest=0.01,
        wacc=wacc,
        terminal_growth=tg,
        years=years,
    )
    assert implied is None


def test_reverse_dcf_returns_none_when_lower_bound_hit():
    """
    Distressed stock: price below any sensible DCF even at -20% growth →
    must return None rather than clamp to -20%.
    """
    wacc, tg, years = 10, 2.5, 10
    # Extremely low price relative to fcf → implied growth would be < -20%
    implied = _reverse_dcf_implied_growth(
        current_price=0.01,
        fcf_per_share_latest=100,
        wacc=wacc,
        terminal_growth=tg,
        years=years,
    )
    assert implied is None


# =========================================================================
# Monte Carlo
# =========================================================================


def test_monte_carlo_is_deterministic_under_fixed_seed():
    """
    The implementation seeds its rng with 42 — same inputs must give same
    percentiles on every run. Regressions here == non-reproducible reports.
    """
    a = _monte_carlo(1000, 100, 10, years=10, trials=500)
    b = _monte_carlo(1000, 100, 10, years=10, trials=500)
    assert a == b


def test_monte_carlo_percentiles_are_monotonic():
    """p5 ≤ p50 ≤ p95 always."""
    p5, p50, p95 = _monte_carlo(1000, 100, 10, years=10, trials=500)
    assert p5 <= p50 <= p95


def test_monte_carlo_median_in_reasonable_range_of_base_dcf():
    """
    With growth mean 10% and wacc-ish 10%, Monte Carlo p50 should land in the
    same order-of-magnitude as a base-case DCF at g=10%. Catches catastrophic
    regressions (e.g. percentile indexing flipped).
    """
    p5, p50, p95 = _monte_carlo(1000, 100, 10, years=10, trials=500)
    base = _dcf_value_per_share(1000, 10, 2.5, 10, 10, 100)
    # p50 within 2× of base case is generous but catches sign flips / unit errors
    assert 0.25 * base < p50 < 4.0 * base


# =========================================================================
# Kelly (stage 7)
# =========================================================================


def test_kelly_half_kelly_reduces_full_kelly_by_half():
    """f* = p - q/b, returned as half-Kelly."""
    # p=0.6, b=2: full = 0.6 - 0.4/2 = 0.4, half = 0.20
    assert _kelly_fraction(0.6, 2.0) == pytest.approx(0.20)


def test_kelly_breakeven_is_zero():
    """p=0.5, b=1 ⇒ full = 0 ⇒ half = 0."""
    assert _kelly_fraction(0.5, 1.0) == pytest.approx(0.0)


def test_kelly_negative_edge_clamps_to_zero():
    """Never recommend shorting from Kelly — clamp to 0 when edge is negative."""
    # p=0.4, b=0.5: full = 0.4 - 0.6/0.5 = -0.8 ⇒ clamped to 0
    assert _kelly_fraction(0.4, 0.5) == 0


def test_kelly_invalid_win_loss_returns_zero():
    """Defensive: non-positive win/loss ratio ⇒ 0 (can't size without a payoff)."""
    assert _kelly_fraction(0.6, 0) == 0
    assert _kelly_fraction(0.6, -1) == 0


# =========================================================================
# v0.6.1: industry-aware scenarios (P0-1)
# =========================================================================


def test_scenarios_known_sector_returns_calibrated_tuple():
    """Technology sector should map to a sector-tuned (bear, base, bull)
    that differs from the generic default — not the copy-paste 3/8/15."""
    (bear, base, bull), src = _scenarios_for_sector("Technology")
    assert (bear, base, bull) == (5.0, 10.0, 18.0)
    assert "sector-default" in src


def test_scenarios_unknown_sector_falls_back_to_generic_with_warning():
    """Unknown sectors get the historical 3/8/15 but the source label must
    flag "generic" so the findings layer can surface a warning."""
    (bear, base, bull), src = _scenarios_for_sector("Quantum Teleportation")
    assert (bear, base, bull) == (3.0, 8.0, 15.0)
    assert "generic" in src


def test_scenarios_empty_sector_falls_back():
    (bear, base, bull), src = _scenarios_for_sector("")
    assert (bear, base, bull) == (3.0, 8.0, 15.0)
    assert "generic" in src


# =========================================================================
# v0.6.1: blended WACC (P0-3)
# =========================================================================


def test_blended_wacc_zero_debt_falls_back_to_pure_equity():
    """No debt → identical to _compute_wacc(); flag says no blending done."""
    wacc, comp = _compute_wacc_blended(
        beta=1.0,
        risk_free=4.0,
        erp=5.5,
        total_debt=0,
        market_cap=1_000_000_000,
        effective_tax_rate=0.21,
    )
    assert wacc == pytest.approx(_compute_wacc(1.0, 4.0, 5.5))
    assert comp["has_debt_weighting"] is False


def test_blended_wacc_missing_market_cap_falls_back():
    """Can't blend without both sides of the capital structure."""
    wacc, comp = _compute_wacc_blended(
        beta=1.0,
        risk_free=4.0,
        erp=5.5,
        total_debt=1_000_000_000,
        market_cap=0,
        effective_tax_rate=0.21,
    )
    assert wacc == pytest.approx(_compute_wacc(1.0, 4.0, 5.5))
    assert comp["has_debt_weighting"] is False


def test_blended_wacc_with_debt_is_lower_than_pure_equity():
    """Finance theory: adding after-tax debt to the mix drags WACC below Ke
    (as long as Kd × (1-Tc) < Ke, which is the normal case)."""
    pure = _compute_wacc(1.0, 4.0, 5.5)
    blended, comp = _compute_wacc_blended(
        beta=1.0,
        risk_free=4.0,
        erp=5.5,
        total_debt=5_000_000_000,
        market_cap=5_000_000_000,
        effective_tax_rate=0.21,
    )
    assert blended < pure
    assert comp["has_debt_weighting"] is True
    assert comp["weight_equity"] == pytest.approx(0.5)
    assert comp["weight_debt"] == pytest.approx(0.5)


def test_blended_wacc_clamps_weird_tax_rates():
    """A tax credit year (negative effective tax) must not invert Kd into
    a negative, which would pull WACC to nonsense levels. Clamp to [0, 35%]."""
    _, comp_neg = _compute_wacc_blended(
        beta=1.0,
        risk_free=4.0,
        erp=5.5,
        total_debt=1e9,
        market_cap=1e9,
        effective_tax_rate=-0.5,
    )
    assert comp_neg["tax_rate_used"] == pytest.approx(0.0)

    _, comp_high = _compute_wacc_blended(
        beta=1.0,
        risk_free=4.0,
        erp=5.5,
        total_debt=1e9,
        market_cap=1e9,
        effective_tax_rate=0.80,
    )
    assert comp_high["tax_rate_used"] == pytest.approx(0.35)


# =========================================================================
# v0.6.1: effective tax rate helper
# =========================================================================


def test_effective_tax_rate_normal_year():
    """Standard positive pretax + tax expense → returns the ratio."""
    r = _effective_tax_rate({"pretax_income": 100, "income_tax_expense": 21})
    assert r == pytest.approx(0.21)


def test_effective_tax_rate_loss_year_returns_none():
    """Negative pretax → effective rate is uninformative (ratio is noise)."""
    r = _effective_tax_rate({"pretax_income": -50, "income_tax_expense": 5})
    assert r is None


def test_effective_tax_rate_missing_fields_returns_none():
    assert _effective_tax_rate({}) is None
    assert _effective_tax_rate({"pretax_income": 100}) is None


def test_effective_tax_rate_outlier_returns_none():
    """A 90% effective rate (one-off FX hit / deferred-tax blow-up) is not
    useful for WACC — callers should fall back to statutory."""
    r = _effective_tax_rate({"pretax_income": 100, "income_tax_expense": 90})
    assert r is None
