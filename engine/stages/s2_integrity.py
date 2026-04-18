"""
Stage 2: Integrity / Lie Detector.

Philosophy: Before spending time on qualitative analysis, verify the numbers
aren't cooked. Catches Enron-style accounting before you fall in love.

Rules:
- Accrual Ratio = (NI - OCF) / Total Assets < 10%, trending down
- Capex / Depreciation ≥ 100% (not milking old assets)
- Goodwill / Total Assets < 20% (organic growth, not M&A patchwork)
- OCF > Net Income (cash quality)
- No audit qualifications
"""
from __future__ import annotations

import time

from engine.models import StageResult, Verdict
from engine.providers import financial_datasets as fd
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 2
STAGE_NAME = "诚实度测谎"


def run(cfg: Config, keys: ApiKeys, ticker: str) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=3)
        balance = fd.fetch_balance_sheets(cfg, keys, ticker, period="annual", limit=3)
        cashflow = fd.fetch_cash_flow_statements(cfg, keys, ticker, period="annual", limit=3)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    metrics = []
    findings = []

    if not (income.periods and balance.periods and cashflow.periods):
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=["Missing statement data"],
            elapsed_seconds=time.time() - t0,
        )

    inc0 = income.periods[0]
    bal0 = balance.periods[0]
    cf0 = cashflow.periods[0]

    ni = inc0.get("net_income") or 0
    ocf = cf0.get("net_cash_flow_from_operations") or 0
    total_assets = bal0.get("total_assets") or 0

    # --- Accrual Ratio ---
    if total_assets > 0:
        accrual = (ni - ocf) / total_assets * 100
        metrics.append(make_metric(
            "Accrual Ratio", round(accrual, 2),
            "< 10% (越低越好)", abs(accrual) < 10, unit="%",
            note="(净利润 - 经营现金流) / 总资产",
        ))

    # --- OCF vs Net Income ---
    if ni > 0:
        ocf_ratio = ocf / ni
        metrics.append(make_metric(
            "OCF / Net Income", round(ocf_ratio, 2),
            "> 1.0", ocf_ratio > 1.0, unit="x",
            note="<1 则质疑利润质量 —— 利润未转化为现金",
        ))

    # --- Capex / Depreciation ---
    capex = abs(cf0.get("capital_expenditure") or 0)
    da = inc0.get("depreciation_and_amortization") or 0
    if da > 0 and capex > 0:
        capex_dep = capex / da
        metrics.append(make_metric(
            "Capex / Depreciation", round(capex_dep, 2),
            "≥ 1.0", capex_dep >= 1.0, unit="x",
            note="< 1 则公司在吃老本，设备旧了不换" if capex_dep < 1 else "维持性资本支出充分",
        ))

    # --- Goodwill / Total Assets ---
    goodwill = bal0.get("goodwill") or 0
    if total_assets > 0:
        gw_ratio = goodwill / total_assets * 100
        metrics.append(make_metric(
            "Goodwill / Total Assets", round(gw_ratio, 1),
            "< 20%", gw_ratio < 20, unit="%",
            note="过高说明靠并购拼凑成长，而非有机增长",
        ))

    # --- Trend check on accrual ratio (3-year trend) ---
    if len(income.periods) >= 3 and len(cashflow.periods) >= 3 and len(balance.periods) >= 3:
        accruals = []
        for i, b, c in zip(income.periods[:3], balance.periods[:3], cashflow.periods[:3]):
            ta = b.get("total_assets") or 0
            if ta > 0:
                a = ((i.get("net_income") or 0) - (c.get("net_cash_flow_from_operations") or 0)) / ta * 100
                accruals.append(a)
        if len(accruals) == 3:
            trend_rising = accruals[0] > accruals[1] > accruals[2]
            metrics.append(make_metric(
                "Accrual 趋势 (3Y)", f"{accruals[2]:.1f}% → {accruals[1]:.1f}% → {accruals[0]:.1f}%",
                "非上升", not trend_rising,
                note="上升趋势 = 利润质量恶化" if trend_rising else "趋势稳定或下降",
            ))

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "net_income": ni,
            "ocf": ocf,
            "capex": capex,
            "da": da,
            "goodwill": goodwill,
            "total_assets": total_assets,
        },
        elapsed_seconds=time.time() - t0,
    )
