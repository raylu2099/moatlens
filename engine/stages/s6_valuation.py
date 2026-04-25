"""
Stage 6: Valuation (DCF + Reverse DCF + Monte Carlo).

Philosophy: Only compute intrinsic value after Stages 1-5 pass. The worst
mistake is falling in love with cheap price before confirming quality.

Three valuation methods (all must agree or flag disagreement):
1. DCF with 3 scenarios (bear/base/bull), growth rates calibrated by sector
2. Reverse DCF: what growth does current price imply?
3. Monte Carlo: sensitivity over 500 random paths (parameter-uncertainty
   distribution — distinct from the discrete bear/base/bull scenarios)

WACC: CAPM cost of equity (Rf + β × ERP) blended with after-tax cost of
debt when the balance sheet carries meaningful debt. Pure-equity fallback
when debt data is missing, with an explicit finding so the user knows.

v0.6.1 audit fixes bundled here:
- P0-1: industry-aware bear/base/bull growth (was hardcoded 3/8/15 for all)
- P0-3: WACC now blends debt weighting
- P1-1: WACC ≤ terminal-growth now emits an explicit finding (no silent 0)
- P2-1: Monte Carlo vs bear/base/bull are now labeled as different objects
- P2-3: reverse-DCF out-of-bracket emits a finding (was silently omitted)
"""

from __future__ import annotations

import random
import time

from engine.models import StageResult, ValuationOutput, ValuationScenario, Verdict
from engine.providers import financial_datasets as fd
from engine.providers import fred as p_fred
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric

STAGE_ID = 6
STAGE_NAME = "估值 (DCF + 反向 DCF + Monte Carlo)"


# --- P0-1: Industry-aware scenarios ---------------------------------------
#
# Growth rates below are 10Y base-case FCF CAGR anchors for each sector,
# hand-picked from a mix of Damodaran industry averages and the visible
# shape of US large-cap cohorts over 2015-2025. These are DEFAULTS, not
# a substitute for peer-calibrated numbers — the per-ticker right answer
# is "median of closest 5 peers," which we don't have infrastructure for
# yet. When sector is unknown, we fall back to the historical hardcoded
# (3, 8, 15) but emit a warning so the user knows the IV is anchored to
# a generic assumption.
#
# Tuple shape: (bear_g, base_g, bull_g) — annual FCF growth in %.
_SECTOR_SCENARIO_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "Technology": (5.0, 10.0, 18.0),
    "Communication Services": (3.0, 7.0, 12.0),
    "Healthcare": (3.0, 8.0, 14.0),
    "Financial Services": (2.0, 5.0, 9.0),
    "Consumer Cyclical": (2.0, 6.0, 11.0),
    "Consumer Defensive": (1.0, 4.0, 7.0),
    "Industrials": (2.0, 5.0, 9.0),
    "Energy": (0.0, 3.0, 7.0),
    "Basic Materials": (1.0, 4.0, 8.0),
    "Utilities": (1.0, 3.0, 5.0),
    "Real Estate": (1.0, 3.0, 5.0),
}
_GENERIC_SCENARIOS = (3.0, 8.0, 15.0)


def _scenarios_for_sector(sector: str) -> tuple[tuple[float, float, float], str]:
    """Return (bear, base, bull) growth plus a provenance label.

    The provenance string is surfaced in findings so the user sees whether
    the scenarios are sector-tuned or generic."""
    if sector in _SECTOR_SCENARIO_DEFAULTS:
        return _SECTOR_SCENARIO_DEFAULTS[sector], f"sector-default ({sector})"
    return _GENERIC_SCENARIOS, "generic-default (sector unknown — use with caution)"


# --- WACC -----------------------------------------------------------------


def _compute_wacc(beta: float | None, risk_free: float, erp: float = 5.5) -> float:
    """
    Pure-equity WACC: Ke = Rf + β × ERP.

    Kept as a thin function for legacy callers and numerical-regression
    tests. For a debt-carrying firm, prefer `_compute_wacc_blended`.
    """
    b = beta if beta is not None else 1.0
    return risk_free + b * erp


def _compute_wacc_blended(
    beta: float | None,
    risk_free: float,
    erp: float,
    total_debt: float,
    market_cap: float,
    effective_tax_rate: float,
    credit_spread_pct: float = 2.0,
) -> tuple[float, dict]:
    """
    Blended WACC: Ke × E/(D+E) + Kd × (1-Tc) × D/(D+E).

    - Ke via CAPM (same as `_compute_wacc`)
    - Kd approximated as Rf + `credit_spread_pct`. Using a fixed 200 bps
      default covers investment-grade borrowers reasonably; distressed or
      sub-IG firms will have their WACC understated, which makes DCF
      optimistic. The finding output surfaces the Kd used so a careful
      reader can sanity-check.
    - Tc is the *effective* tax rate from the income statement, clamped
      to [0%, 35%] to guard against one-offs (tax credit refunds, foreign
      mix shifts) producing nonsense.

    Returns (wacc_pct, detail_dict). The detail dict feeds a findings
    line and the raw_data snapshot.
    """
    ke = _compute_wacc(beta, risk_free, erp)
    components = {
        "ke_pct": ke,
        "kd_pct": None,
        "tax_rate_used": None,
        "weight_equity": 1.0,
        "weight_debt": 0.0,
        "has_debt_weighting": False,
        "credit_spread_assumed_pct": credit_spread_pct,
    }

    if total_debt <= 0 or market_cap <= 0:
        # No material debt (or no market-cap data) → pure-equity WACC.
        return ke, components

    tax_rate = max(0.0, min(0.35, effective_tax_rate or 0.21))
    kd = risk_free + credit_spread_pct
    total_capital = total_debt + market_cap
    we = market_cap / total_capital
    wd = total_debt / total_capital
    wacc = ke * we + kd * (1.0 - tax_rate) * wd

    components.update(
        {
            "kd_pct": kd,
            "tax_rate_used": tax_rate,
            "weight_equity": we,
            "weight_debt": wd,
            "has_debt_weighting": True,
        }
    )
    return wacc, components


# --- DCF ------------------------------------------------------------------


def _dcf_value_per_share(
    fcf_latest: float,
    growth_rate: float,
    terminal_growth: float,
    wacc: float,
    years: int,
    shares_outstanding: float,
) -> float:
    """Project FCF years ahead, discount, add terminal value.

    Returns 0.0 in the Gordon-growth edge case (WACC ≤ terminal_growth).
    Callers inspecting scenarios should detect 0 and emit a finding
    (see P1-1 handling in `run()`) rather than pretend 0 is "cheap."
    """
    if shares_outstanding <= 0 or wacc <= terminal_growth:
        return 0.0

    pv = 0.0
    fcf = fcf_latest
    for y in range(1, years + 1):
        fcf *= 1 + growth_rate / 100
        pv += fcf / (1 + wacc / 100) ** y

    terminal = fcf * (1 + terminal_growth / 100) / (wacc / 100 - terminal_growth / 100)
    pv += terminal / (1 + wacc / 100) ** years

    return pv / shares_outstanding


_REVERSE_DCF_LO = -20.0
_REVERSE_DCF_HI = 100.0
_REVERSE_DCF_BOUNDARY_EPS = 0.5  # within 0.5% of a bound = didn't converge


def _reverse_dcf_implied_growth(
    current_price: float,
    fcf_per_share_latest: float,
    wacc: float,
    terminal_growth: float,
    years: int = 10,
) -> float | None:
    """
    Binary search for the growth rate that makes DCF ≈ current price.

    Returns None if the answer lies outside the search bracket
    [_REVERSE_DCF_LO, _REVERSE_DCF_HI] — either the stock is so cheap it
    implies growth < -20% (catastrophic expectations) or so hot it implies
    growth > 100% (meme/pre-revenue). A clamped-to-boundary number is worse
    than None because it looks like a real answer.
    """
    if fcf_per_share_latest <= 0 or current_price <= 0:
        return None

    lo, hi = _REVERSE_DCF_LO, _REVERSE_DCF_HI
    for _ in range(50):
        mid = (lo + hi) / 2
        pv = 0.0
        fcf = fcf_per_share_latest
        for y in range(1, years + 1):
            fcf *= 1 + mid / 100
            pv += fcf / (1 + wacc / 100) ** y
        if wacc / 100 > terminal_growth / 100:
            terminal = fcf * (1 + terminal_growth / 100) / (wacc / 100 - terminal_growth / 100)
            pv += terminal / (1 + wacc / 100) ** years
        if pv > current_price:
            hi = mid
        else:
            lo = mid

    answer = (lo + hi) / 2
    # Converged at a bracket bound → answer is unreliable
    if (answer - _REVERSE_DCF_LO) < _REVERSE_DCF_BOUNDARY_EPS:
        return None
    if (_REVERSE_DCF_HI - answer) < _REVERSE_DCF_BOUNDARY_EPS:
        return None
    return answer


def _monte_carlo(
    fcf_latest: float,
    shares_outstanding: float,
    base_wacc: float,
    years: int = 10,
    trials: int = 500,
) -> tuple[float, float, float]:
    """Return (p5, p50, p95) intrinsic values per share.

    NOTE: these percentiles describe a **parameter-uncertainty distribution**
    — what would IV look like if our growth / terminal / WACC guesses were
    off by typical amounts? They are NOT the same object as bear/base/bull,
    which are discrete strategic scenarios ("what if competition compresses
    margins vs. what if AI tailwind compounds"). Users should read:
      - bear/base/bull → "what story do we tell?"
      - p5/p50/p95   → "given the story, how much does parameter noise matter?"
    """
    values = []
    rng = random.Random(42)
    for _ in range(trials):
        growth = rng.gauss(10, 5)  # mean 10%, std 5%
        growth = max(-5, min(35, growth))
        tg = rng.gauss(2.5, 0.5)
        tg = max(0, min(4, tg))
        wacc = max(base_wacc + rng.gauss(0, 1), tg + 0.5)

        v = _dcf_value_per_share(fcf_latest, growth, tg, wacc, years, shares_outstanding)
        values.append(v)

    values.sort()
    p5 = values[int(trials * 0.05)]
    p50 = values[int(trials * 0.50)]
    p95 = values[int(trials * 0.95)]
    return p5, p50, p95


# --- Helpers for run() ----------------------------------------------------


def _effective_tax_rate(income_period: dict) -> float | None:
    """Derive effective tax rate from income statement. Returns None when
    inputs are missing or nonsensical (negative pretax income, etc.).
    Caller decides a fallback."""
    pretax = income_period.get("pretax_income") or income_period.get("income_before_tax")
    tax = income_period.get("income_tax_expense")
    if pretax is None or tax is None:
        return None
    if pretax <= 0:
        return None  # loss-making year → effective tax rate is noise
    try:
        rate = float(tax) / float(pretax)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    # Clamp obvious outliers
    if rate < -0.1 or rate > 0.5:
        return None
    return rate


def run(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    tech_mode: bool = False,
) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=1)
        cashflow = fd.fetch_cash_flow_statements(cfg, keys, ticker, period="annual", limit=1)
        balance = fd.fetch_balance_sheets(cfg, keys, ticker, period="annual", limit=1)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID,
            stage_name=STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    multiples = yfp.fetch_multiples(ticker)
    current_price = yfp.fetch_current_price(ticker)
    company_info = yfp.fetch_company_info(ticker)
    sector = (company_info.get("sector") or "").strip()

    metrics = []
    findings = []

    # R3-3: yfinance silently returns None on rate-limit / network / HTML
    # responses (no exception raised). Surface this loudly instead of letting
    # the DCF math run on zero-substituted inputs and emit a garbage IV.
    yf_unreachable = (
        current_price is None
        and multiples.market_cap is None
        and multiples.shares_outstanding is None
    )
    if yf_unreachable:
        return StageResult(
            stage_id=STAGE_ID,
            stage_name=STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=[
                "⚠️ yfinance unreachable — 无法获取当前价、市值、流通股数。"
                "可能是 Yahoo 限流或被 GFW 拦截。稍后重试或检查代理。",
                f"诊断: multiples.err={multiples.err or 'None'}",
            ],
            elapsed_seconds=time.time() - t0,
        )

    if not (cashflow.periods and income.periods and multiples.shares_outstanding):
        return StageResult(
            stage_id=STAGE_ID,
            stage_name=STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=["Missing required data for DCF"],
            elapsed_seconds=time.time() - t0,
        )

    cf0 = cashflow.periods[0]
    inc0 = income.periods[0]
    bal0 = balance.periods[0] if balance.periods else {}

    fcf_latest = cf0.get("free_cash_flow") or (
        (cf0.get("net_cash_flow_from_operations") or 0) - abs(cf0.get("capital_expenditure") or 0)
    )
    if tech_mode:
        sbc = cf0.get("share_based_compensation") or 0
        fcf_latest -= sbc

    shares = multiples.shares_outstanding or 0
    fcf_per_share = fcf_latest / shares if shares > 0 else 0

    # --- WACC (blended when debt is material) ---
    risk_free = p_fred.fetch_risk_free_rate(cfg, keys)
    beta = multiples.beta or 1.0
    total_debt = bal0.get("total_debt") or 0
    market_cap = multiples.market_cap or 0
    eff_tax = _effective_tax_rate(inc0) or 0.21  # fallback to 21% US statutory

    wacc, wacc_components = _compute_wacc_blended(
        beta=beta,
        risk_free=risk_free,
        erp=5.5,
        total_debt=total_debt,
        market_cap=market_cap,
        effective_tax_rate=eff_tax,
    )

    if wacc_components["has_debt_weighting"]:
        findings.append(
            f"**WACC 组件**: Ke={wacc_components['ke_pct']:.2f}% (Rf {risk_free:.2f}% + β {beta:.2f} × ERP 5.5%), "
            f"Kd={wacc_components['kd_pct']:.2f}% (Rf + 2%{'假设投资级利差' if True else ''}), "
            f"Tc={wacc_components['tax_rate_used']*100:.1f}% (有效税率)"
        )
        findings.append(
            f"  权重: 股本 {wacc_components['weight_equity']*100:.1f}% / 债务 {wacc_components['weight_debt']*100:.1f}% "
            f"→ **WACC = {wacc:.2f}%**"
        )
    else:
        findings.append(
            f"**WACC 组件**: Rf {risk_free:.2f}% + β {beta:.2f} × ERP 5.5% = **{wacc:.2f}%** "
            f"(纯股本 WACC — {'无显著债务' if total_debt == 0 else '缺 market cap / debt 数据，未做加权'})"
        )

    # R3-7: non-US ticker WACC bias warning. WACC components are calibrated
    # to the US market: 10Y Treasury risk-free, 5.5% US ERP, 21% US tax rate.
    # For a Chinese, European, or Japanese company, these inputs systematically
    # under- or over-state the discount rate and the resulting IV is biased.
    # Surface this as a finding so the user discounts the number rather than
    # treating it as authoritative.
    country = (company_info.get("country") or "").strip()
    non_us_country = country and country not in {"United States", "USA", "US", ""}
    if non_us_country:
        findings.append(
            f"⚠️ **非美股 WACC 偏差**: {ticker} 注册地 {country}。"
            "WACC 组件（risk-free 10Y UST、ERP 5.5%、税率 21%）按美国市场校准，"
            "对非美企业（不同央行政策利率、不同 country risk premium、不同企业税率）"
            "得到的 IV 系统性偏差。把这个数字当参考而非定论。"
        )

    # --- 3 scenarios (industry-aware) ---
    (bear_g, base_g, bull_g), scenario_source = _scenarios_for_sector(sector)
    findings.append(
        f"**增长假设来源**: {scenario_source} "
        f"→ bear {bear_g}% / base {base_g}% / bull {bull_g}%"
    )
    if "generic" in scenario_source:
        findings.append(
            "  ⚠️ 使用通用增长假设 — yfinance 未返回 sector 或该 sector 不在配置表。"
            "得到的 IV 对 AAPL 这类公司并未做行业校准，谨慎使用。"
        )
    scenarios = [
        ("bear", bear_g, 2.0, wacc + 1.0),
        ("base", base_g, 2.5, wacc),
        ("bull", bull_g, 3.0, max(wacc - 0.5, 2.6)),
    ]
    scenario_outputs = []
    wacc_too_low_for_terminal: list[str] = []
    for label, g, tg, w in scenarios:
        # P1-1: detect Gordon-growth degenerate case explicitly per scenario.
        if w <= tg:
            wacc_too_low_for_terminal.append(f"{label.upper()} (WACC {w:.2f}% ≤ 终值增 {tg}%)")
        iv = _dcf_value_per_share(fcf_latest, g, tg, w, 10, shares)
        scenario_outputs.append(
            ValuationScenario(
                label=label,
                fcf_growth_rate=g,
                terminal_growth=tg,
                wacc=w,
                intrinsic_value_per_share=iv,
            )
        )
        findings.append(
            f"  {label.upper()}: FCF 年增 {g}%, 终值增 {tg}%, WACC {w:.2f}% " f"→ IV ${iv:.2f}"
        )

    if wacc_too_low_for_terminal:
        findings.append(
            "⚠️ **Gordon 增长失效**: "
            + ", ".join(wacc_too_low_for_terminal)
            + " — 该场景的 IV 置为 $0，并非便宜。高成长公司应重新校准 WACC 或重看 beta。"
        )

    base_iv = scenario_outputs[1].intrinsic_value_per_share

    # --- Reverse DCF ---
    implied_growth = _reverse_dcf_implied_growth(
        current_price or 0,
        fcf_per_share,
        wacc,
        2.5,
        years=10,
    )
    if implied_growth is not None:
        findings.append(
            f"**反向 DCF**: 当前价 ${current_price:.2f} 隐含未来 10 年 FCF 年增 **{implied_growth:.1f}%**"
        )
        metrics.append(
            make_metric(
                "隐含增长率 (反向 DCF)",
                round(implied_growth, 1),
                "合理区间 5-15%",
                5 <= implied_growth <= 15,
                unit="%",
                note="远低于历史 = 安全边际；远高于历史 = 贵",
            )
        )
    else:
        # P2-3: make the "out of bracket" case explicit instead of silently
        # dropping the line. Users otherwise wonder "why no reverse DCF here?"
        findings.append(
            "**反向 DCF**: 无解 — 当前价 / FCF 暗示隐含增长超出 [-20%, 100%] 区间。"
            "可能原因：股价极端高估（meme / pre-revenue）、FCF 被一次性事件压低、或 WACC/Kd 校准偏离。"
        )

    # --- Monte Carlo ---
    p5, p50, p95 = _monte_carlo(fcf_latest, shares, wacc, years=10, trials=500)
    findings.append(
        f"**Monte Carlo 敏感度** (500 次随机参数采样，**与 bear/base/bull 是两种不同对象**): "
        f"P5 ${p5:.2f} / P50 ${p50:.2f} / P95 ${p95:.2f}"
    )
    findings.append(
        "  注: bear/base/bull = 离散战略场景（你讲的故事）；"
        "MC P5/P50/P95 = 参数不确定性分布（故事成立时，增长/WACC 抖动带来多大 IV 波动）。"
    )

    # --- Current price vs base IV ---
    if current_price and base_iv > 0:
        discount_pct = (base_iv - current_price) / base_iv * 100
        metrics.append(
            make_metric(
                "当前价 vs 基准 IV",
                f"${current_price:.2f} / ${base_iv:.2f}",
                "IV 至少高出 20% (buffer)",
                discount_pct >= 20,
                note=f"折让 {discount_pct:.1f}%"
                if discount_pct >= 0
                else f"溢价 {abs(discount_pct):.1f}%",
            )
        )

    # --- Valuation multiples check (historical percentile) ---
    if multiples.trailing_pe:
        metrics.append(
            make_metric(
                "Trailing P/E",
                round(multiples.trailing_pe, 1),
                "行业依赖",
                None,  # not binary
            )
        )
    if multiples.forward_pe:
        metrics.append(
            make_metric(
                "Forward P/E",
                round(multiples.forward_pe, 1),
                "< 25 (非高成长) | < 35 (高成长)",
                multiples.forward_pe < (35 if tech_mode else 25),
            )
        )

    valuation = ValuationOutput(
        current_price=current_price,
        dcf_scenarios=scenario_outputs,
        reverse_dcf_implied_growth=implied_growth,
        monte_carlo_p5=p5,
        monte_carlo_p50=p50,
        monte_carlo_p95=p95,
    )

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "wacc": wacc,
            "wacc_components": wacc_components,
            "risk_free_rate": risk_free,
            "beta": beta,
            "fcf_latest": fcf_latest,
            "fcf_per_share": fcf_per_share,
            "shares_outstanding": shares,
            "sector": sector,
            "scenario_source": scenario_source,
            "total_debt": total_debt,
            "market_cap": market_cap,
            "effective_tax_rate_used": eff_tax,
            "valuation": valuation.model_dump(),
        },
        elapsed_seconds=time.time() - t0,
    )
