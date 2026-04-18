"""
Orchestrator — runs the 8-stage audit.

Two modes:
- run_audit_auto(): run all stages, no user interaction (for batch/API/web)
- run_audit_wizard(): yields StageResult after each stage for interactive
  approval (CLI wizard)

Supports resume from partial audit via saved AuditReport checkpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Generator

from engine.models import Action, AuditReport, ConfidenceLevel, StageResult, Thesis, Verdict
from engine.providers import yfinance_provider as yfp
from engine.stages import (
    s1_competence, s2_integrity, s3_moat,
    s4_capital, s5_owner_earnings, s6_valuation,
    s7_safety, s8_inversion,
)
from shared.config import ApiKeys, Config


STAGES = [
    ("s1", s1_competence.run),
    ("s2", s2_integrity.run),
    ("s3", s3_moat.run),
    ("s4", s4_capital.run),
    ("s5", s5_owner_earnings.run),
    ("s6", s6_valuation.run),
    ("s7", s7_safety.run),
    ("s8", s8_inversion.run),
]


def _new_report(ticker: str, anchor_thesis: str = "") -> AuditReport:
    company = yfp.fetch_company_info(ticker)
    return AuditReport(
        ticker=ticker.upper(),
        company_name=company.get("long_name", ticker),
        audit_date=datetime.now().strftime("%Y-%m-%d"),
        generated_at=datetime.now(),
        anchor_thesis=anchor_thesis,
    )


def _compute_final_verdict(report: AuditReport) -> tuple[Action, ConfidenceLevel]:
    """Roll up 8 stages into final action + confidence."""
    pass_count = sum(1 for s in report.stages if s.verdict == Verdict.PASS)
    fail_count = sum(1 for s in report.stages if s.verdict == Verdict.FAIL)
    total = len([s for s in report.stages if s.verdict != Verdict.SKIP])

    # Critical stages: 1, 2, 7 failing = AVOID
    critical_stages = {1, 2, 7}
    critical_fail = any(
        s.stage_id in critical_stages and s.verdict == Verdict.FAIL
        for s in report.stages
    )

    if critical_fail or fail_count >= 3:
        action = Action.AVOID
    elif pass_count >= 6:
        # Check margin of safety from stage 7
        s7 = next((s for s in report.stages if s.stage_id == 7), None)
        mos = s7.raw_data.get("margin_of_safety_pct", 0) if s7 else 0
        if mos >= 30:
            action = Action.BUY
        elif mos >= 0:
            action = Action.WATCH
        else:
            action = Action.HOLD
    else:
        action = Action.WATCH

    # Confidence
    if pass_count >= 7 and fail_count == 0:
        confidence = ConfidenceLevel.HIGH
    elif fail_count >= 2:
        confidence = ConfidenceLevel.LOW
    else:
        confidence = ConfidenceLevel.MEDIUM

    return action, confidence


def _build_thesis(report: AuditReport) -> Thesis:
    """Populate Thesis from final audit results."""
    s7 = next((s for s in report.stages if s.stage_id == 7), None)
    s3 = next((s for s in report.stages if s.stage_id == 3), None)
    s4 = next((s for s in report.stages if s.stage_id == 4), None)
    s8 = next((s for s in report.stages if s.stage_id == 8), None)

    current = s7.raw_data.get("current_price") if s7 else None
    target_buy = s7.raw_data.get("target_buy") if s7 else None
    target_sell = s7.raw_data.get("target_sell") if s7 else None

    moat_summary = ""
    if s3 and s3.raw_data.get("claude_parsed"):
        moat_summary = s3.raw_data["claude_parsed"].get("summary_cn", "")

    mgmt_summary = ""
    if s4 and s4.raw_data.get("claude_parsed"):
        mgmt_summary = s4.raw_data["claude_parsed"].get("summary_cn", "")

    invalidations = []
    if s8 and s8.raw_data.get("failure_modes"):
        for fm in s8.raw_data["failure_modes"][:3]:
            invalidations.append(fm.get("scenario", ""))

    return Thesis(
        ticker=report.ticker,
        entry_date=report.audit_date,
        entry_price=current,
        target_buy_price=target_buy,
        target_sell_price=target_sell,
        one_sentence_thesis=report.anchor_thesis,
        invalidation_conditions=invalidations,
        review_cadence="quarterly",
        moat_assessment=moat_summary[:300],
        management_note=mgmt_summary[:300],
    )


def run_audit_auto(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
    progress_callback: Callable[[int, StageResult], None] | None = None,
) -> AuditReport:
    """Run all 8 stages without user interaction. Returns full report."""
    report = _new_report(ticker, anchor_thesis)

    # Stage 1
    s1 = s1_competence.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s1)
    _track_cost(report, s1)
    if progress_callback: progress_callback(1, s1)

    # Stage 2
    s2 = s2_integrity.run(cfg, keys, ticker)
    report.stages.append(s2)
    _track_cost(report, s2)
    if progress_callback: progress_callback(2, s2)

    # Stage 3
    s3 = s3_moat.run(cfg, keys, ticker, s1.raw_data, tech_mode=tech_mode)
    report.stages.append(s3)
    _track_cost(report, s3)
    if progress_callback: progress_callback(3, s3)

    # Stage 4
    s4 = s4_capital.run(cfg, keys, ticker, s1.raw_data)
    report.stages.append(s4)
    _track_cost(report, s4)
    if progress_callback: progress_callback(4, s4)

    # Stage 5
    s5 = s5_owner_earnings.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s5)
    _track_cost(report, s5)
    if progress_callback: progress_callback(5, s5)

    # Stage 6
    s6 = s6_valuation.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s6)
    _track_cost(report, s6)
    if progress_callback: progress_callback(6, s6)

    # Stage 7
    s7 = s7_safety.run(cfg, keys, ticker, s6.raw_data)
    report.stages.append(s7)
    _track_cost(report, s7)
    if progress_callback: progress_callback(7, s7)

    # Stage 8
    prior = {
        f"stage{s.stage_id}": s.raw_data
        for s in [s3, s4, s6, s7]
    }
    s8 = s8_inversion.run(cfg, keys, ticker, anchor_thesis, prior)
    report.stages.append(s8)
    _track_cost(report, s8)
    if progress_callback: progress_callback(8, s8)

    # Final verdict
    report.overall_action, report.overall_confidence = _compute_final_verdict(report)
    report.thesis = _build_thesis(report)

    # Collect inversion failure modes
    if s8.raw_data.get("failure_modes"):
        report.inversion_failure_modes = [
            fm.get("scenario", "") for fm in s8.raw_data["failure_modes"]
        ]
    if s8.raw_data.get("variant_view"):
        report.variant_view = s8.raw_data["variant_view"]

    return report


def run_audit_wizard(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
) -> Generator[tuple[int, StageResult, AuditReport], bool, AuditReport]:
    """
    Interactive wizard: yields (stage_num, result, partial_report) after each stage.
    Caller sends True to continue, False to abort.
    """
    report = _new_report(ticker, anchor_thesis)

    # Stage 1
    s1 = s1_competence.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s1)
    _track_cost(report, s1)
    cont = yield 1, s1, report
    if not cont: return report

    # Stage 2
    s2 = s2_integrity.run(cfg, keys, ticker)
    report.stages.append(s2)
    _track_cost(report, s2)
    cont = yield 2, s2, report
    if not cont: return report

    # Stage 3
    s3 = s3_moat.run(cfg, keys, ticker, s1.raw_data, tech_mode=tech_mode)
    report.stages.append(s3)
    _track_cost(report, s3)
    cont = yield 3, s3, report
    if not cont: return report

    # Stage 4
    s4 = s4_capital.run(cfg, keys, ticker, s1.raw_data)
    report.stages.append(s4)
    _track_cost(report, s4)
    cont = yield 4, s4, report
    if not cont: return report

    # Stage 5
    s5 = s5_owner_earnings.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s5)
    _track_cost(report, s5)
    cont = yield 5, s5, report
    if not cont: return report

    # Stage 6
    s6 = s6_valuation.run(cfg, keys, ticker, tech_mode=tech_mode)
    report.stages.append(s6)
    _track_cost(report, s6)
    cont = yield 6, s6, report
    if not cont: return report

    # Stage 7
    s7 = s7_safety.run(cfg, keys, ticker, s6.raw_data)
    report.stages.append(s7)
    _track_cost(report, s7)
    cont = yield 7, s7, report
    if not cont: return report

    # Stage 8
    prior = {f"stage{s.stage_id}": s.raw_data for s in [s3, s4, s6, s7]}
    s8 = s8_inversion.run(cfg, keys, ticker, anchor_thesis, prior)
    report.stages.append(s8)
    _track_cost(report, s8)
    yield 8, s8, report

    # Finalize
    report.overall_action, report.overall_confidence = _compute_final_verdict(report)
    report.thesis = _build_thesis(report)
    if s8.raw_data.get("failure_modes"):
        report.inversion_failure_modes = [fm.get("scenario", "") for fm in s8.raw_data["failure_modes"]]
    if s8.raw_data.get("variant_view"):
        report.variant_view = s8.raw_data["variant_view"]

    return report


def _track_cost(report: AuditReport, stage: StageResult) -> None:
    cost = stage.raw_data.get("cost_usd", 0) or 0
    report.total_api_cost_usd += cost
    key = f"stage{stage.stage_id}"
    report.provider_costs[key] = cost
