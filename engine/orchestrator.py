"""
Orchestrator — runs the 8-stage audit.

Two modes (single code path, different consumption):
- run_audit_auto(): run all stages, return full report (callback per stage)
- run_audit_wizard(): generator yielding after each stage (CLI interactive)

Hardening:
- Per-stage exceptions become Verdict.SKIP with the reason in findings —
  one bad stage no longer crashes the whole audit.
- --resume support via resume_from: caller passes an AuditReport with
  partial stages; orchestrator continues from the next stage.
"""
from __future__ import annotations

import traceback
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


def _stage1(cfg, keys, ticker, tech_mode, prior):
    return s1_competence.run(cfg, keys, ticker, tech_mode=tech_mode)

def _stage2(cfg, keys, ticker, tech_mode, prior):
    return s2_integrity.run(cfg, keys, ticker)

def _stage3(cfg, keys, ticker, tech_mode, prior):
    return s3_moat.run(cfg, keys, ticker, prior.get(1, {}), tech_mode=tech_mode)

def _stage4(cfg, keys, ticker, tech_mode, prior):
    return s4_capital.run(cfg, keys, ticker, prior.get(1, {}))

def _stage5(cfg, keys, ticker, tech_mode, prior):
    return s5_owner_earnings.run(cfg, keys, ticker, tech_mode=tech_mode)

def _stage6(cfg, keys, ticker, tech_mode, prior):
    return s6_valuation.run(cfg, keys, ticker, tech_mode=tech_mode)

def _stage7(cfg, keys, ticker, tech_mode, prior):
    return s7_safety.run(cfg, keys, ticker, prior.get(6, {}))

def _stage8(cfg, keys, ticker, tech_mode, prior, anchor_thesis=""):
    prior_for_s8 = {f"stage{k}": v for k, v in prior.items() if k in (3, 4, 6, 7)}
    return s8_inversion.run(cfg, keys, ticker, anchor_thesis, prior_for_s8)


STAGES: list[tuple[int, Callable]] = [
    (1, _stage1),
    (2, _stage2),
    (3, _stage3),
    (4, _stage4),
    (5, _stage5),
    (6, _stage6),
    (7, _stage7),
    (8, _stage8),
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
    pass_count = sum(1 for s in report.stages if s.verdict == Verdict.PASS)
    fail_count = sum(1 for s in report.stages if s.verdict == Verdict.FAIL)

    critical_stages = {1, 2, 7}
    critical_fail = any(
        s.stage_id in critical_stages and s.verdict == Verdict.FAIL
        for s in report.stages
    )

    if critical_fail or fail_count >= 3:
        action = Action.AVOID
    elif pass_count >= 6:
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

    if pass_count >= 7 and fail_count == 0:
        confidence = ConfidenceLevel.HIGH
    elif fail_count >= 2:
        confidence = ConfidenceLevel.LOW
    else:
        confidence = ConfidenceLevel.MEDIUM

    return action, confidence


def _build_thesis(report: AuditReport) -> Thesis:
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


def _track_cost(report: AuditReport, stage: StageResult) -> None:
    cost = stage.raw_data.get("cost_usd", 0) or 0
    report.total_api_cost_usd += cost
    report.provider_costs[f"stage{stage.stage_id}"] = cost


def _run_stage_safe(
    stage_id: int, fn: Callable, cfg, keys, ticker, tech_mode, prior, anchor_thesis,
) -> StageResult:
    """Run a stage with a hard safety net — any exception becomes SKIP."""
    try:
        if stage_id == 8:
            return fn(cfg, keys, ticker, tech_mode, prior, anchor_thesis=anchor_thesis)
        return fn(cfg, keys, ticker, tech_mode, prior)
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return StageResult(
            stage_id=stage_id,
            stage_name=f"Stage {stage_id}",
            verdict=Verdict.SKIP,
            findings=[f"⚠️ Stage raised {type(e).__name__}: {e}", f"```\n{tb}\n```"],
            raw_data={"error": str(e), "error_type": type(e).__name__},
        )


def _finalize(report: AuditReport) -> AuditReport:
    report.overall_action, report.overall_confidence = _compute_final_verdict(report)
    report.thesis = _build_thesis(report)
    s8 = next((s for s in report.stages if s.stage_id == 8), None)
    if s8 and s8.raw_data.get("failure_modes"):
        report.inversion_failure_modes = [
            fm.get("scenario", "") for fm in s8.raw_data["failure_modes"]
        ]
    if s8 and s8.raw_data.get("variant_view"):
        report.variant_view = s8.raw_data["variant_view"]
    return report


def run_audit_auto(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
    progress_callback: Callable[[int, StageResult], None] | None = None,
    resume_from: AuditReport | None = None,
) -> AuditReport:
    """Run all 8 stages. If resume_from is provided, skip stages already in it."""
    report = resume_from or _new_report(ticker, anchor_thesis)
    done_ids = {s.stage_id for s in report.stages}
    prior = {s.stage_id: s.raw_data for s in report.stages}

    for sid, fn in STAGES:
        if sid in done_ids:
            continue
        result = _run_stage_safe(sid, fn, cfg, keys, ticker, tech_mode, prior, anchor_thesis)
        report.stages.append(result)
        _track_cost(report, result)
        prior[sid] = result.raw_data
        if progress_callback:
            progress_callback(sid, result)

    return _finalize(report)


def run_audit_wizard(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
    resume_from: AuditReport | None = None,
) -> Generator[tuple[int, StageResult, AuditReport], bool, AuditReport]:
    """Interactive wizard: yield after each stage; caller sends True/False to continue."""
    report = resume_from or _new_report(ticker, anchor_thesis)
    done_ids = {s.stage_id for s in report.stages}
    prior = {s.stage_id: s.raw_data for s in report.stages}

    for sid, fn in STAGES:
        if sid in done_ids:
            continue
        result = _run_stage_safe(sid, fn, cfg, keys, ticker, tech_mode, prior, anchor_thesis)
        report.stages.append(result)
        _track_cost(report, result)
        prior[sid] = result.raw_data
        cont = yield sid, result, report
        if cont is False:
            return report

    return _finalize(report)
