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
"""
from __future__ import annotations

import time
from statistics import mean, stdev

from engine.models import StageResult, Verdict
from engine.providers import financial_datasets as fd
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 5
STAGE_NAME = "所有者盈利 & 财务质量"


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


def _dupont(income: dict, balance: dict) -> dict:
    """DuPont ROE = Net margin × Asset turnover × Leverage."""
    ni = income.get("net_income") or 0
    revenue = income.get("revenue") or 1
    total_assets = balance.get("total_assets") or 1
    equity = balance.get("shareholders_equity") or 1

    net_margin = ni / revenue * 100
    asset_turnover = revenue / total_assets
    leverage = total_assets / equity
    roe = net_margin * asset_turnover * leverage / 100

    return {
        "net_margin_pct": net_margin,
        "asset_turnover": asset_turnover,
        "leverage": leverage,
        "roe_pct": roe,
    }


def run(
    cfg: Config, keys: ApiKeys, ticker: str, tech_mode: bool = False,
) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=5)
        balance = fd.fetch_balance_sheets(cfg, keys, ticker, period="annual", limit=5)
        cashflow = fd.fetch_cash_flow_statements(cfg, keys, ticker, period="annual", limit=5)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    if not (income.periods and balance.periods and cashflow.periods):
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=["Incomplete statement data"],
            elapsed_seconds=time.time() - t0,
        )

    metrics = []
    findings = []

    # --- Owner Earnings for each of last 3Y ---
    oe_series = []
    oe_details = []
    for i, (inc, cf) in enumerate(zip(income.periods[:3], cashflow.periods[:3])):
        oe, detail = _compute_owner_earnings(inc, cf, subtract_sbc=tech_mode)
        oe_series.append(oe)
        oe_details.append(detail)

    if oe_series:
        latest_oe = oe_series[0]
        latest_rev = income.periods[0].get("revenue") or 0
        if latest_rev > 0:
            oe_margin = latest_oe / latest_rev * 100
            metrics.append(make_metric(
                "Owner Earnings Margin", round(oe_margin, 1),
                "≥ 15%", oe_margin >= 15, unit="%",
                note=f"Tech mode (扣 SBC): {tech_mode}",
            ))

        # All 3Y positive?
        all_positive = all(o > 0 for o in oe_series)
        metrics.append(make_metric(
            "Owner Earnings (3Y)", f"{[round(o/1e9, 2) for o in oe_series]} B",
            "全部 > 0", all_positive,
        ))

    # --- SBC as % of revenue (tech stock red flag) ---
    if tech_mode and oe_details:
        sbc_latest = oe_details[0].get("sbc", 0)
        rev_latest = income.periods[0].get("revenue") or 1
        sbc_pct = sbc_latest / rev_latest * 100
        metrics.append(make_metric(
            "SBC / Revenue", round(sbc_pct, 1),
            "< 10% (科技股红线)", sbc_pct < 10, unit="%",
            note="股权激励稀释风险" if sbc_pct >= 10 else "稀释可控",
        ))

    # --- FCF Margin stability ---
    fcf_margins = []
    for inc, cf in zip(income.periods[:5], cashflow.periods[:5]):
        rev = inc.get("revenue") or 0
        fcf = cf.get("free_cash_flow") or (
            (cf.get("net_cash_flow_from_operations") or 0)
            - abs(cf.get("capital_expenditure") or 0)
        )
        if rev > 0:
            fcf_margins.append(fcf / rev * 100)

    if len(fcf_margins) >= 3:
        avg_margin = mean(fcf_margins)
        stddev = stdev(fcf_margins) if len(fcf_margins) >= 2 else 0
        metrics.append(make_metric(
            "FCF Margin 平均", round(avg_margin, 1),
            "≥ 15%", avg_margin >= 15, unit="%",
        ))
        cv = stddev / avg_margin if avg_margin > 0 else 999
        metrics.append(make_metric(
            "FCF Margin 稳定性 (CV)", round(cv, 2),
            "< 0.3 (越稳越好)", cv < 0.3,
            note="变异系数；<0.3 表示利润质量稳定",
        ))

    # --- DuPont ---
    dupont = _dupont(income.periods[0], balance.periods[0])
    if dupont.get("net_margin_pct") is not None:
        findings.append(
            f"**DuPont 拆解**: Net Margin {dupont['net_margin_pct']:.1f}% × "
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
        invested = (bal0.get("total_debt") or 0) + (bal0.get("shareholders_equity") or 0) - (bal0.get("cash_and_equivalents") or 0)
        if invested > 0:
            roic = ebit * 0.79 / invested * 100  # after-tax proxy
            roe = dupont.get("roe_pct", 0)
            ratio = roe / roic if roic > 0 else None
            if ratio:
                metrics.append(make_metric(
                    "ROE / ROIC", round(ratio, 2),
                    "< 1.5 (无杠杆幻觉)", ratio < 1.5,
                    note=f"ROIC {roic:.1f}%, ROE {roe:.1f}%",
                ))
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
