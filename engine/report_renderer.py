"""
Render AuditReport → Markdown for human reading.
The same renderer output is used by CLI, web, and file archive.
"""
from __future__ import annotations

from engine.models import AuditReport, StageResult, Verdict


VERDICT_EMOJI = {
    Verdict.PASS: "✅",
    Verdict.BORDERLINE: "🟡",
    Verdict.FAIL: "❌",
    Verdict.SKIP: "⊘",
}


def render_markdown(report: AuditReport) -> str:
    lines = []
    lines.append(f"# Moatlens Audit — {report.ticker}")
    lines.append(f"**{report.company_name}** · {report.audit_date}")
    lines.append("")

    if report.anchor_thesis:
        lines.append(f"> **你的初始论点**: {report.anchor_thesis}")
        lines.append("")

    # Overall verdict
    action = report.overall_action.value if report.overall_action else "PENDING"
    conf = report.overall_confidence.value if report.overall_confidence else "?"
    pass_count = sum(1 for s in report.stages if s.verdict == Verdict.PASS)
    lines.append(f"## 📋 总体判断: **{action}** (置信度 {conf})")
    lines.append(f"8 Stage: {pass_count}/{len(report.stages)} 通过 · API 成本 ${report.total_api_cost_usd:.3f}")
    lines.append("")

    # Thesis summary
    if report.thesis:
        t = report.thesis
        lines.append("### 💼 持仓建议")
        if t.entry_price:
            lines.append(f"- 当前价: ${t.entry_price:.2f}")
        if t.target_buy_price:
            lines.append(f"- 🟢 理想买入: ≤ ${t.target_buy_price:.2f}")
        if t.target_sell_price:
            lines.append(f"- 🔴 开始减仓: ≥ ${t.target_sell_price:.2f}")
        if t.invalidation_conditions:
            lines.append("- ⚠️ 失效条件:")
            for c in t.invalidation_conditions:
                lines.append(f"  - {c}")
        lines.append(f"- 🔄 复盘节奏: {t.review_cadence}")
        lines.append("")

    # Per-stage
    for stage in report.stages:
        lines.append("---")
        lines.append("")
        icon = VERDICT_EMOJI.get(stage.verdict, "?")
        lines.append(f"## Stage {stage.stage_id}: {stage.stage_name} {icon} {stage.verdict.value}")
        lines.append("")

        if stage.metrics:
            lines.append("| 指标 | 值 | 阈值 | 通过 |")
            lines.append("|---|---|---|---|")
            for m in stage.metrics:
                val = m.value if m.value is not None else "—"
                unit = f" {m.unit}" if m.unit else ""
                pass_icon = "✅" if m.pass_ is True else ("❌" if m.pass_ is False else "—")
                note = f" *{m.note}*" if m.note else ""
                lines.append(f"| {m.name} | {val}{unit} | {m.threshold} | {pass_icon}{note} |")
            lines.append("")

        if stage.findings:
            for f in stage.findings:
                lines.append(f)
            lines.append("")

        if stage.human_decision:
            lines.append(f"> 👤 **人工判断**: {stage.human_decision}")
            lines.append("")

    # Inversion summary
    if report.inversion_failure_modes:
        lines.append("---")
        lines.append("")
        lines.append("## 🔄 Munger Inversion 总结")
        lines.append("")
        lines.append("**这笔投资可能怎样失败：**")
        for fm in report.inversion_failure_modes:
            lines.append(f"- {fm}")
        lines.append("")

    if report.variant_view:
        lines.append("## 🎯 Variant View Canvas")
        lines.append("")
        for k, v in report.variant_view.items():
            if v:
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Audit snapshot link (the full JSON lives alongside as <ticker>/<date>.json
    # — don't embed 50KB of JSON inside the human-readable markdown)
    lines.append("---")
    lines.append("")
    lines.append(
        f"📦 完整 audit snapshot 见 `{report.ticker}/{report.audit_date}.json` "
        "(同目录下的 JSON 文件) —— 可用于 diff 或第三方工具分析。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*教育性分析，不构成投资建议。自行决策。*")

    return "\n".join(lines)


def render_summary_line(report: AuditReport) -> str:
    """One-line summary for lists / Telegram."""
    action = report.overall_action.value if report.overall_action else "PENDING"
    pass_count = sum(1 for s in report.stages if s.verdict == Verdict.PASS)
    return f"{report.ticker} · {action} · {pass_count}/{len(report.stages)} stages · ${report.total_api_cost_usd:.2f}"
