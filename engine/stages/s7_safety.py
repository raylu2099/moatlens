"""
Stage 7: Margin of Safety & Asymmetry (Howard Marks lens).

Philosophy: After valuation, buy only if price is well below intrinsic value.
Howard Marks: "The goal is risk-adjusted return. Avoid losing permanent
capital — everything else follows."

Compute:
- Target buy price = base IV × 0.7
- Target aggressive buy = base IV × 0.5 (load up)
- Target sell price = base IV × 1.1
- Kelly fraction for position sizing
- Asymmetry: upside vs downside
- Howard Marks "correct × non-consensus" framing
"""
from __future__ import annotations

import time

from engine.models import StageResult, Verdict
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 7
STAGE_NAME = "安全边际 & 非对称性"


def _kelly_fraction(win_prob: float, win_loss_ratio: float) -> float:
    """Half-Kelly for practical use. f* = p - q/b, then × 0.5."""
    if win_loss_ratio <= 0:
        return 0
    q = 1 - win_prob
    full = win_prob - q / win_loss_ratio
    return max(0, full * 0.5)


def run(
    cfg: Config, keys: ApiKeys, ticker: str,
    stage6_raw: dict,
) -> StageResult:
    t0 = time.time()

    val = stage6_raw.get("valuation", {})
    scenarios = val.get("dcf_scenarios", [])
    current_price = val.get("current_price")

    metrics = []
    findings = []

    if not scenarios or not current_price:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=["No valuation data from Stage 6"],
            elapsed_seconds=time.time() - t0,
        )

    # Extract scenario values
    bear = next((s for s in scenarios if s["label"] == "bear"), None)
    base = next((s for s in scenarios if s["label"] == "base"), None)
    bull = next((s for s in scenarios if s["label"] == "bull"), None)

    base_iv = base["intrinsic_value_per_share"] if base else 0
    bear_iv = bear["intrinsic_value_per_share"] if bear else 0
    bull_iv = bull["intrinsic_value_per_share"] if bull else 0

    if base_iv <= 0:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=["Base intrinsic value not positive"],
            elapsed_seconds=time.time() - t0,
        )

    # --- Target prices ---
    target_buy = base_iv * 0.7
    target_aggressive = base_iv * 0.5
    target_sell = base_iv * 1.1

    findings.append(f"**当前价**: ${current_price:.2f}")
    findings.append(f"**基准 IV**: ${base_iv:.2f}")
    findings.append("")
    findings.append(f"🟢 **理想买入**: ≤ ${target_buy:.2f} (IV × 0.7)")
    findings.append(f"🚀 **激进加仓**: ≤ ${target_aggressive:.2f} (IV × 0.5，双倍仓位)")
    findings.append(f"🔴 **开始减仓**: ≥ ${target_sell:.2f} (IV × 1.1)")

    # --- Margin of safety (current) ---
    mos_pct = (base_iv - current_price) / base_iv * 100
    metrics.append(make_metric(
        "当前安全边际", round(mos_pct, 1),
        "≥ 30%", mos_pct >= 30, unit="%",
        note="< 0 = 溢价交易；0-30% = 公允；≥ 30% = 有 buffer",
    ))

    # --- Asymmetry: upside / downside ---
    upside = (bull_iv - current_price) / current_price * 100 if bull_iv > 0 else 0
    downside = (current_price - bear_iv) / current_price * 100 if bear_iv > 0 else 0
    asymmetry = upside / downside if downside > 0 else float("inf")

    findings.append("")
    findings.append(f"**非对称性分析**:")
    findings.append(f"  Bull 上行空间: {upside:+.1f}%")
    findings.append(f"  Bear 下行空间: {downside:+.1f}%")
    findings.append(f"  非对称比例: {asymmetry:.1f}x (>1 = 好赔率)")

    metrics.append(make_metric(
        "非对称比例 (Upside/Downside)", round(asymmetry, 1) if asymmetry != float('inf') else "∞",
        "≥ 2x", asymmetry >= 2, unit="x",
    ))

    # --- Kelly fraction (rough estimate) ---
    # Assume 60% confidence in base case if MOS > 20%
    # Win/loss ratio from upside/downside
    if downside > 0:
        win_prob = 0.55 if mos_pct >= 30 else 0.50
        win_loss = upside / downside
        kelly = _kelly_fraction(win_prob, win_loss)
        kelly_pct = kelly * 100
        findings.append("")
        findings.append(f"**Kelly 仓位建议** (half-Kelly, 保守):")
        findings.append(f"  假设胜率 {win_prob*100:.0f}% + 赔率 {win_loss:.1f}")
        findings.append(f"  → 建议仓位 **{kelly_pct:.1f}%** of portfolio")
        if kelly_pct < 2:
            findings.append("  💡 Kelly 接近 0 — 收益不足补偿风险，可能该跳过")
        elif kelly_pct > 10:
            findings.append("  ⚠️ Kelly > 10% — 建议封顶 10%，避免单票风险过大")

    # --- Howard Marks lens ---
    findings.append("")
    findings.append("**Howard Marks 检查**: ")
    findings.append(
        "  超额收益 = **正确** × **非共识**。"
        f"基准 IV ${base_iv:.2f} 是你的判断。"
    )
    if mos_pct >= 30:
        findings.append(
            f"  当前价 ${current_price:.2f} (折让 {mos_pct:.0f}%) 暗示市场更悲观。"
            "如果市场错了、你对，你获得超额收益。问：市场为什么悲观？你的反方观点是什么？"
        )
    elif mos_pct < 0:
        findings.append(
            f"  当前价 ${current_price:.2f} (溢价 {abs(mos_pct):.0f}%) 暗示市场比你乐观。"
            "**红旗**：你是否把 consensus 当成自己的判断？为何你认为 IV 应更高？"
        )
    else:
        findings.append(
            f"  市场与你判断基本一致。没有 alpha 可言 — "
            "要么等更好价格，要么找真正非共识的机会。"
        )

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "current_price": current_price,
            "base_iv": base_iv,
            "target_buy": target_buy,
            "target_aggressive": target_aggressive,
            "target_sell": target_sell,
            "margin_of_safety_pct": mos_pct,
            "upside_pct": upside,
            "downside_pct": downside,
            "asymmetry_ratio": asymmetry if asymmetry != float("inf") else 99,
            "kelly_fraction_pct": kelly_pct if 'kelly_pct' in locals() else None,
        },
        elapsed_seconds=time.time() - t0,
    )
