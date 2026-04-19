"""
Stream adapter — wrap the orchestrator's wizard generator into an event
stream suitable for SSE (web) or terminal streaming.

Events emitted (tuples of (kind, payload)):
- ("session_started", {"ticker", "session_id"})
- ("stage_start",     {"stage_id", "stage_name"})
- ("stage_complete",  {"stage_id", "stage_name", "verdict", "metrics", "findings"})
- ("commentary",      {"stage_id", "text"})
- ("quote",           {"stage_id", "quote": {id, author, text_cn, text_en, source}})
- ("final",           {"action", "confidence", "pass_count", "report_date",
                       "total_cost_usd", "inversion_failure_modes", ...})
- ("error",           {"message"})
"""
from __future__ import annotations

from typing import Iterator

from engine import wisdom
from engine.coach import commentary
from engine.models import AuditReport, StageResult, Verdict
from engine.orchestrator import run_audit_wizard
from engine.report_renderer import render_markdown
from shared.chat import ChatMessage, ChatSession, save_session
from shared.config import ApiKeys, Config
from shared.storage import save_audit


Event = tuple[str, dict]


def stream_audit(
    cfg: Config, keys: ApiKeys, session: ChatSession,
    skip_claude: bool = False,
) -> Iterator[Event]:
    """
    Drive the existing wizard generator, inject commentary + quote events
    after each stage, persist the session state as we go, finally save the
    audit report and emit ('final', ...).
    """
    session.audit_status = "running"
    save_session(cfg, session)

    yield "session_started", {
        "ticker": session.ticker,
        "session_id": session.session_id,
    }

    try:
        gen = run_audit_wizard(
            cfg, keys, session.ticker,
            anchor_thesis=session.anchor_thesis,
            tech_mode=session.tech_mode,
            skip_claude=skip_claude,
            my_market_expectation=session.my_market_expectation,
            my_variant_view=session.my_variant_view,
        )
        used_quote_ids: set[str] = set()
        report: AuditReport | None = None

        # Emit stage_start before first stage
        yield "stage_start", {"stage_id": 1, "stage_name": _stage_name(1)}

        while True:
            try:
                stage_id, result, partial_report = next(gen) if report is None else gen.send(True)
            except StopIteration as e:
                report = e.value if e.value else partial_report
                break

            session.current_stage = stage_id
            session.add(ChatMessage.new(
                "coach",
                _stage_summary_line(result),
                stage_id=stage_id,
            ))

            yield "stage_complete", {
                "stage_id": stage_id,
                "stage_name": result.stage_name,
                "verdict": result.verdict.value,
                "metrics": [
                    {
                        "name": m.name, "value": m.value, "unit": m.unit,
                        "threshold": m.threshold, "pass": m.pass_, "note": m.note,
                    }
                    for m in result.metrics
                ],
                "findings": list(result.findings),
            }

            # Pick a quote for this stage, exclude already-used
            q = wisdom.pick_for_stage(cfg, stage_id, session.session_id, exclude_ids=used_quote_ids)
            if q:
                used_quote_ids.add(q.id)
                yield "quote", {
                    "stage_id": stage_id,
                    "quote": {
                        "id": q.id, "author": q.author,
                        "text_en": q.text_en, "text_cn": q.text_cn,
                        "source": q.source, "themes": q.themes,
                    },
                }

            # Generate commentary (Haiku or rule)
            commentary_text = commentary(
                cfg, keys, result, q,
                user_context=session.anchor_thesis,
            )
            session.add(ChatMessage.new(
                "coach", commentary_text,
                stage_id=stage_id,
                quote_id=q.id if q else "",
            ))
            save_session(cfg, session)
            yield "commentary", {"stage_id": stage_id, "text": commentary_text}

            # Emit next stage_start unless this was stage 8
            if stage_id < 8:
                yield "stage_start", {
                    "stage_id": stage_id + 1,
                    "stage_name": _stage_name(stage_id + 1),
                }

        if report is None:
            yield "error", {"message": "No report produced"}
            session.audit_status = "error"
            save_session(cfg, session)
            return

        # Persist audit
        md = render_markdown(report)
        save_audit(cfg, report, md)
        session.report_date = report.audit_date
        session.audit_status = "complete"
        session.current_stage = 9

        # Trigger-based closing quote (decision-point wisdom)
        closing_trigger = _closing_trigger(report)
        closing_quote = None
        if closing_trigger:
            closing_quote = wisdom.pick_for_trigger(
                cfg, closing_trigger, session.session_id, exclude_ids=used_quote_ids,
            )
        if closing_quote:
            yield "quote", {
                "stage_id": 9,
                "quote": {
                    "id": closing_quote.id, "author": closing_quote.author,
                    "text_en": closing_quote.text_en, "text_cn": closing_quote.text_cn,
                    "source": closing_quote.source, "themes": closing_quote.themes,
                },
            }

        yield "final", {
            "ticker": report.ticker,
            "action": report.overall_action.value if report.overall_action else "",
            "confidence": report.overall_confidence.value if report.overall_confidence else "",
            "pass_count": sum(1 for s in report.stages if s.verdict == Verdict.PASS),
            "stage_count": len(report.stages),
            "report_date": report.audit_date,
            "total_cost_usd": float(report.total_api_cost_usd or 0),
            "inversion_failure_modes": report.inversion_failure_modes[:3],
            "munger_questions": _munger_questions(report),
        }
        save_session(cfg, session)
    except Exception as e:
        session.audit_status = "error"
        save_session(cfg, session)
        yield "error", {"message": f"{type(e).__name__}: {e}"}


# =====================================================================
# Helpers
# =====================================================================

_STAGE_NAMES = {
    1: "能力圈 & 垃圾桶测试",
    2: "诚实度测谎",
    3: "护城河深度验证",
    4: "管理层 & 资本配置",
    5: "所有者盈利 & 财务质量",
    6: "估值 (DCF + 反向 DCF + Monte Carlo)",
    7: "安全边际 & 非对称性",
    8: "反方论点 & Variant View",
}


def _stage_name(sid: int) -> str:
    return _STAGE_NAMES.get(sid, f"Stage {sid}")


def _stage_summary_line(result: StageResult) -> str:
    """One-line Chinese log-style summary of a stage for session transcript."""
    pass_ct = sum(1 for m in result.metrics if m.pass_ is True)
    total = sum(1 for m in result.metrics if m.pass_ is not None)
    if total:
        return f"Stage {result.stage_id} {result.stage_name}: {result.verdict.value} ({pass_ct}/{total} 指标通过)"
    return f"Stage {result.stage_id} {result.stage_name}: {result.verdict.value}"


def _closing_trigger(report: AuditReport) -> str:
    """Pick a decision-point trigger based on final verdict + MOS."""
    action = report.overall_action.value if report.overall_action else ""
    mos = 0
    s7 = next((s for s in report.stages if s.stage_id == 7), None)
    if s7 and s7.raw_data.get("margin_of_safety_pct") is not None:
        mos = s7.raw_data["margin_of_safety_pct"]
    if action == "BUY":
        if mos < 10:
            return "low_mos_buy"
        return "action_buy"
    if action == "AVOID":
        return "action_avoid"
    if action == "WATCH":
        return "watch_long"
    if mos >= 30:
        return "high_mos"
    return ""


def _munger_questions(report: AuditReport) -> list[str]:
    """Return 3 Munger-style self-questions tailored to this audit."""
    qs = [
        "如果这笔投资 5 年后失败，最可能的原因是什么？",
        "市场比我看得更透的可能是什么？我凭什么认为我对？",
        "如果我明天就要把这笔投资原原本本讲给一个不懂金融的朋友听，哪个环节我讲不清？",
    ]
    # Customize if we have inversion failure modes
    if report.inversion_failure_modes:
        fm = report.inversion_failure_modes[0]
        qs[0] = f"Stage 8 标出的最大失败模式是「{fm[:60]}」—— 未来 6 个月哪个信号会让你知道它正在发生？"
    return qs
