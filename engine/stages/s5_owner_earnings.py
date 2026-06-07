"""
Stage 5: Owner Earnings & Financial Quality.

Philosophy: Buffett explicitly rejects EPS as "accounting noise". He wants
Owner Earnings = Net Income + D&A ± Non-cash items - Maintenance Capex.
For tech stocks: **MUST** subtract Stock-Based Compensation (biggest trap).

Rules:
- Owner Earnings > 0 (last 3Y stable)
- Owner Earnings Margin = OE / Revenue ≥ 15% (20%+ is world class)
- FCF Margin stability (std dev / mean low)
- DuPont decomposition: high NPM (Buffett loves) vs high leverage (hates)
- ROIC > ROE (no leverage illusion)

v0.6.1 audit fixes bundled here:
- P0-2: flag maintenance-CapEx uncertainty for high-capex industries
- P1-2: DuPont uses (begin + end)/2 average assets when 2 periods available
- P2-2: ROIC uses effective tax rate from income statement (was hardcoded 21%)
"""

from __future__ import annotations

import time
from statistics import mean, stdev

from engine.models import StageResult, Verdict
from engine.providers import financial_datasets as fd
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric

STAGE_ID = 5
STAGE_NAME = "所有者盈利 & 财务质量"


# Industries where maintenance-CapEx ≈ D&A is a **bad** approximation. These
# businesses run on long-lived physical infrastructure whose replacement
# cost often exceeds accounting depreciation (inflation, regulatory upgrades,
# capacity growth disguised as maintenance). Buffett's shortcut formula
# understates true maintenance spend here → overstates Owner Earnings.
#
# Matched against yfinance `info.sector` (broad) and `info.industry`
# (narrow). Either match triggers the warning.
_HIGH_CAPEX_SECTORS = frozenset(
    {
        "Energy",
        "Utilities",
        "Basic Materials",
        "Real Estate",
    }
)
_HIGH_CAPEX_INDUSTRY_KEYWORDS = (
    "semiconductor",
    "airlines",
    "railroads",
    "marine shipping",
    "steel",
    "integrated freight",
    "oil & gas",
    "telecom",
    "specialty industrial machinery",
)


def _is_high_capex(sector: str, industry: str) -> bool:
    if sector in _HIGH_CAPEX_SECTORS:
        return True
    ind = (industry or "").lower()
    return any(kw in ind for kw in _HIGH_CAPEX_INDUSTRY_KEYWORDS)


def _effective_tax_rate_from_income(inc: dict) -> float | None:
    """Derive effective tax rate from income statement. Returns None when
    inputs are missing or nonsensical (loss year, outlier >35%).

    Duplicated from s6 on purpose: keeps each stage self-contained so a
    future split across separate services doesn't create a dependency
    chain across modules. Two small copies cost less than one abstraction
    everyone imports through."""
    pretax = inc.get("pretax_income") or inc.get("income_before_tax")
    tax = inc.get("income_tax_expense")
    if pretax is None or tax is None or pretax <= 0:
        return None
    try:
        rate = float(tax) / float(pretax)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if rate < 0 or rate > 0.5:
        return None
    return rate


def _compute_owner_earnings(
    income: dict, cashflow: dict, subtract_sbc: bool = True
) -> tuple[float, dict]:
    """
    Owner Earnings = Net Income
                   + D&A
                   + Other non-cash
                   - Maintenance Capex
                   - (Stock-Based Comp if tech, per Buffett's 2019 letter)

    We approximate maintenance capex as Depreciation (conservative).
    """
    ni = income.get("net_income") or 0
    da = income.get("depreciation_and_amortization") or 0
    capex_total = abs(cashflow.get("capital_expenditure") or 0)
    sbc = cashflow.get("share_based_compensation") or 0

    # Maintenance capex proxy ≈ D&A (Buffett's approximation)
    maint_capex = min(capex_total, da) if da > 0 else capex_total * 0.7

    oe = ni + da - maint_capex
    if subtract_sbc:
        oe -= sbc

    return oe, {
        "net_income": ni,
        "da": da,
        "capex_total": capex_total,
        "maintenance_capex_proxy": maint_capex,
        "sbc": sbc,
        "sbc_subtracted": subtract_sbc,
    }


def _dupont(income: dict, balance: dict, balance_prev: dict | None = None) -> dict:
    """DuPont ROE = Net margin × Asset turnover × Leverage.

    When `balance_prev` is provided, uses AVERAGE assets and AVERAGE equity
    = (beginning + ending) / 2, which is the CFA-canonical denominator —
    income is accrued across the year, balance-sheet snapshots are
    point-in-time. Using end-of-period only biases turnover low (and
    leverage high) when the asset base is expanding.

    When `balance_prev` is None, falls back to end-of-period (the pre-v0.6.1
    behavior) so existing numerical-regression tests in tests/test_stage5
    keep pinning the same values without a flag.
    """
    ni = income.get("net_income") or 0
    revenue = income.get("revenue") or 1

    ta_end = balance.get("total_assets") or 1
    eq_end = balance.get("shareholders_equity") or 1

    if balance_prev is not None:
        ta_begin = balance_prev.get("total_assets") or ta_end
        eq_begin = balance_prev.get("shareholders_equity") or eq_end
        total_assets = (ta_end + ta_begin) / 2
        equity = (eq_end + eq_begin) / 2
        used_average = True
    else:
        total_assets = ta_end
        equity = eq_end
        used_average = False

    # Guard against the fallback-1 sentinel collapsing to 0 downstream.
    if total_assets == 0:
        total_assets = 1
    if equity == 0:
        equity = 1

    net_margin = ni / revenue * 100  # %
    asset_turnover = revenue / total_assets
    leverage = total_assets / equity
    # net_margin is already in %, turnover & leverage are unitless ratios →
    # product is ROE already in %, no extra /100 needed.
    roe = net_margin * asset_turnover * leverage

    return {
        "net_margin_pct": net_margin,
        "asset_turnover": asset_turnover,
        "leverage": leverage,
        "roe_pct": roe,
        "used_average_assets": used_average,
    }


def run(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    tech_mode: bool = False,
) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=5)
        balance = fd.fetch_balance_sheets(cfg, keys, ticker, period="annual", limit=5)
        cashflow = fd.fetch_cash_flow_statements(cfg, keys, ticker, period="annual", limit=5)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID,
            stage_name=STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    if not (income.periods and balance.periods and cashflow.periods):
        return StageResult(
            stage_id=STAGE_ID,
            stage_name=STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=["Incomplete statement data"],
            elapsed_seconds=time.time() - t0,
        )

    metrics = []
    findings = []

    # --- P0-2: Maintenance-CapEx uncertainty flag for high-CapEx industries ---
    # Buffett's "maintenance CapEx ≈ D&A" approximation works for asset-light
    # businesses but understates true replacement cost for capital-heavy ones
    # (utilities, energy, telecom, semis, etc.). Surface this caveat so the
    # user reads the OE number with the right skepticism — we don't change
    # the formula (that requires management-guided maintenance-vs-growth
    # capex split, which isn't in our data).
    company_info = yfp.fetch_company_info(ticker)
    sector = (company_info.get("sector") or "").strip()
    industry = (company_info.get("industry") or "").strip()

    # R3-7: pre-revenue biotech / clinical-stage flag. Owner Earnings is a
    # cash-flow-from-mature-operations construct; for a biotech with
    # near-zero revenue and ongoing trial spend, OE is structurally
    # negative and the metric/threshold (`OE margin ≥ 15%`) is meaningless.
    # Don't change the formula — surface the situation so the verdict is
    # read in context (often a venture-style bet, not a value-investing one).
    latest_rev_check = (income.periods[0].get("revenue") or 0) if income.periods else 0
    is_biotech = sector == "Healthcare" and any(
        k in industry.lower() for k in ("biotechnology", "drug manufacturers", "pharmaceutic")
    )
    if is_biotech and latest_rev_check < 50_000_000:  # < $50M = effectively pre-revenue
        findings.append(
            f"⚠️ **临床期/前期生物科技**: {industry} TTM 收入 "
            f"${latest_rev_check / 1e6:.1f}M（< $50M）。"
            "Owner Earnings 在这类标的上结构性为负 — 公司还在烧钱做试验。"
            "用 OE 阈值（≥15% 利润率）评判它没有意义；"
            "应该看 cash runway / pipeline 进展 / 关键试验的相对优势，而不是这页指标。"
        )

    if _is_high_capex(sector, industry):
        findings.append(
            f"⚠️ **维护性 CapEx 不确定性**: {sector or 'unknown'} / {industry or 'unknown'} "
            "属于高资本支出行业，Owner Earnings 使用的 "
            "`maint_capex ≈ min(CapEx, D&A)` 近似会**低估**真实维护支出 "
            "(物理资产重置价常随通胀/监管/产能扩张 > 会计折旧)。"
            "若准备在该标的上押重仓，请人工复核管理层披露的维护性 vs 成长性 CapEx。"
        )

    # --- Owner Earnings for each of last 3Y ---
    oe_series = []
    oe_details = []
    for inc, cf in zip(income.periods[:3], cashflow.periods[:3], strict=False):
        oe, detail = _compute_owner_earnings(inc, cf, subtract_sbc=tech_mode)
        oe_series.append(oe)
        oe_details.append(detail)

    if oe_series:
        latest_oe = oe_series[0]
        latest_rev = income.periods[0].get("revenue") or 0
        if latest_rev > 0:
            oe_margin = latest_oe / latest_rev * 100
            metrics.append(
                make_metric(
                    "Owner Earnings Margin",
                    round(oe_margin, 1),
                    "≥ 15%",
                    oe_margin >= 15,
                    unit="%",
                    note=f"Tech mode (扣 SBC): {tech_mode}",
                )
            )

        # All 3Y positive?
        all_positive = all(o > 0 for o in oe_series)
        metrics.append(
            make_metric(
                "Owner Earnings (3Y)",
                f"{[round(o / 1e9, 2) for o in oe_series]} B",
                "全部 > 0",
                all_positive,
            )
        )

    # --- SBC as % of revenue (tech stock red flag) ---
    if tech_mode and oe_details:
        sbc_latest = oe_details[0].get("sbc", 0)
        rev_latest = income.periods[0].get("revenue") or 1
        sbc_pct = sbc_latest / rev_latest * 100
        metrics.append(
            make_metric(
                "SBC / Revenue",
                round(sbc_pct, 1),
                "< 10% (科技股红线)",
                sbc_pct < 10,
                unit="%",
                note="股权激励稀释风险" if sbc_pct >= 10 else "稀释可控",
            )
        )

    # --- FCF Margin stability ---
    fcf_margins = []
    for inc, cf in zip(income.periods[:5], cashflow.periods[:5], strict=False):
        rev = inc.get("revenue") or 0
        fcf = cf.get("free_cash_flow") or (
            (cf.get("net_cash_flow_from_operations") or 0) - abs(cf.get("capital_expenditure") or 0)
        )
        if rev > 0:
            fcf_margins.append(fcf / rev * 100)

    if len(fcf_margins) >= 3:
        avg_margin = mean(fcf_margins)
        stddev = stdev(fcf_margins) if len(fcf_margins) >= 2 else 0
        metrics.append(
            make_metric(
                "FCF Margin 平均",
                round(avg_margin, 1),
                "≥ 15%",
                avg_margin >= 15,
                unit="%",
            )
        )
        cv = stddev / avg_margin if avg_margin > 0 else 999
        metrics.append(
            make_metric(
                "FCF Margin 稳定性 (CV)",
                round(cv, 2),
                "< 0.3 (越稳越好)",
                cv < 0.3,
                note="变异系数；<0.3 表示利润质量稳定",
            )
        )

    # --- DuPont ---
    # P1-2: pass balance.periods[1] when available so averages are used.
    balance_prev = balance.periods[1] if len(balance.periods) >= 2 else None
    dupont = _dupont(income.periods[0], balance.periods[0], balance_prev=balance_prev)
    if dupont.get("net_margin_pct") is not None:
        avg_tag = " (avg assets)" if dupont.get("used_average_assets") else " (period-end)"
        findings.append(
            f"**DuPont 拆解**{avg_tag}: Net Margin {dupont['net_margin_pct']:.1f}% × "
            f"Asset Turnover {dupont['asset_turnover']:.2f} × "
            f"Leverage {dupont['leverage']:.2f} = ROE {dupont['roe_pct']:.1f}%"
        )
        # Flag leverage-heavy ROE
        if dupont["leverage"] > 3 and dupont["net_margin_pct"] < 10:
            findings.append("⚠️ ROE 主要靠杠杆而非利润率 — Buffett 最讨厌")
        elif dupont["net_margin_pct"] > 20:
            findings.append("✅ 高净利率驱动（Buffett 最爱）")

    # --- ROIC vs ROE (leverage check) ---
    try:
        inc0 = income.periods[0]
        bal0 = balance.periods[0]
        ebit = inc0.get("operating_income") or 0
        invested = (
            (bal0.get("total_debt") or 0)
            + (bal0.get("shareholders_equity") or 0)
            - (bal0.get("cash_and_equivalents") or 0)
        )
        # P2-2: effective tax rate from income statement (was hardcoded 21%/0.79).
        # Falls back to 21% only when the helper returns None.
        eff_tax = _effective_tax_rate_from_income(inc0)
        tax_factor = 1.0 - (eff_tax if eff_tax is not None else 0.21)
        if invested > 0:
            roic = ebit * tax_factor / invested * 100
            roe = dupont.get("roe_pct", 0)
            ratio = roe / roic if roic > 0 else None
            if ratio:
                tax_src = (
                    f"{eff_tax * 100:.1f}% (effective)"
                    if eff_tax is not None
                    else "21% (statutory fallback)"
                )
                metrics.append(
                    make_metric(
                        "ROE / ROIC",
                        round(ratio, 2),
                        "< 1.5 (无杠杆幻觉)",
                        ratio < 1.5,
                        note=f"ROIC {roic:.1f}% @ Tc={tax_src}, ROE {roe:.1f}%",
                    )
                )
    except Exception:
        pass

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "owner_earnings_series_usd": oe_series,
            "owner_earnings_details": oe_details,
            "fcf_margins": fcf_margins,
            "dupont": dupont,
            "tech_mode": tech_mode,
        },
        elapsed_seconds=time.time() - t0,
    )
