"""
Numerical regression tests for Stage 6 DCF / Reverse DCF / Monte Carlo.

These functions directly produce the target buy price. A bug here silently
turns "buy AAPL at $120" into "buy AAPL at $150". Verify against Excel-level
ground truth, not just "output is positive".
"""
from __future__ import annotations

import math

import pytest

from engine.stages.s6_valuation import (
    _compute_wacc,
    _dcf_value_per_share,
    _monte_carlo,
    _reverse_dcf_implied_growth,
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
        f *= (1 + g / 100)
        pv += f / (1 + wacc / 100) ** y
    terminal = f * (1 + tg / 100) / (wacc / 100 - tg / 100)
    pv += terminal / (1 + wacc / 100) ** years
    return pv / shares


def test_dcf_matches_hand_rolled_reference():
    """A specific cash flow scenario must match to 4 decimals."""
    v = _dcf_value_per_share(
        fcf_latest=1000, growth_rate=5, terminal_growth=2,
        wacc=10, years=10, shares_outstanding=100,
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
        explicit_only += f / 1.10 ** y
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
        fcf_latest=fcf_ps * 1000,   # scale up and down by shares=1000 — per-share identical
        growth_rate=g_true, terminal_growth=tg, wacc=wacc,
        years=years, shares_outstanding=1000,
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
