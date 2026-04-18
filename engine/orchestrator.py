"""
Orchestrator — runs the 8-stage audit.

Two modes (single code path, different consumption):
- run_audit_auto(): run all stages, return full report (callback per stage)
- run_audit_wizard(): generator yielding after each stage (CLI interactive)

Knobs for iteration speed:
- skip_claude:  stages 3/4/8 return Verdict.SKIP (free dry-run for testing rule stages)
- only_stages:  list of stage ids — run exactly these (others SKIP, not dropped)
- from_stage:   run this stage and all later ones (earlier ones SKIP if no resume_from)
- resume_from:  previous AuditReport — stages already present are not re-run

Hardening:
- Per-stage exceptions become Verdict.SKIP with the reason in findings.
- Stage 8 is gated on prior-stage signal density to avoid burning Claude on empty data.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from typing import Callable, Generator, Iterable

from engine.models import Action, AuditReport, ConfidenceLevel, StageResult, Thesis, Verdict
from engine.providers import yfinance_provider as yfp
from engine.stages import (
    s1_competence, s2_integrity, s3_moat,
    s4_capital, s5_owner_earnings, s6_valuation,
    s7_safety, s8_inversion,
)
from shared.config import ApiKeys, Config


# Stage IDs that invoke Claude — these are the ones skipped by --no-claude.
CLAUDE_STAGE_IDS = {3, 4, 8}


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

def _stage8(cfg, keys, ticker, tech_mode, prior, anchor_thesis="", my_variant_view=""):
    # Gating: if fewer than 2 of the prior qualitative/valuation stages produced
    # usable data, skip Claude on Stage 8 — otherwise we pay $0.2-0.4 for
    # hallucinated failure modes with no grounding.
    relevant_ids = (3, 4, 6, 7)
    useful = 0
    for sid in relevant_ids:
        raw = prior.get(sid, {}) or {}
        if not raw or raw.get("error"):
            continue
        if (raw.get("claude_parsed") or raw.get("valuation")
                or raw.get("base_iv")
                or raw.get("margin_of_safety_pct") is not None):
            useful += 1

    if useful < 2:
        return StageResult(
            stage_id=8,
            stage_name=s8_inversion.STAGE_NAME,
            verdict=Verdict.SKIP,
            findings=[
                f"⚠️ 跳过 Stage 8：前序 stage 3/4/6/7 中仅 {useful} 个产生可用信号，"
                "Claude 推理缺乏依据。先修复前序 stage 再重跑。",
            ],
            raw_data={"skipped_reason": "insufficient_prior_signals",
                      "useful_prior_count": useful},
        )

    prior_for_s8 = {f"stage{k}": v for k, v in prior.items() if k in relevant_ids}
    return s8_inversion.run(
        cfg, keys, ticker, anchor_thesis, prior_for_s8,
        my_variant_view=my_variant_view,
    )


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


def _new_report(
    ticker: str, anchor_thesis: str = "",
    my_market_expectation: str = "", my_variant_view: str = "",
) -> AuditReport:
    company = yfp.fetch_company_info(ticker)
    return AuditReport(
        ticker=ticker.upper(),
        company_name=company.get("long_name", ticker),
        audit_date=datetime.now().strftime("%Y-%m-%d"),
        generated_at=datetime.now(),
        anchor_thesis=anchor_thesis,
        my_market_expectation=my_market_expectation,
        my_variant_view=my_variant_view,
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
    # Use max so resumed stages don't overwrite with 0.
    key = f"stage{stage.stage_id}"
    report.provider_costs[key] = max(report.provider_costs.get(key, 0.0), cost)


def _run_stage_safe(
    stage_id: int, fn: Callable, cfg, keys, ticker, tech_mode, prior, anchor_thesis,
    my_variant_view: str = "",
) -> StageResult:
    """Run a stage with a hard safety net — any exception becomes SKIP."""
    try:
        if stage_id == 8:
            return fn(cfg, keys, ticker, tech_mode, prior,
                      anchor_thesis=anchor_thesis,
                      my_variant_view=my_variant_view)
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


def _skipped(stage_id: int, reason_cn: str) -> StageResult:
    """Make a synthetic SKIP result (used by --no-claude / --only / --from)."""
    name_map = {
        1: s1_competence.STAGE_NAME, 2: s2_integrity.STAGE_NAME,
        3: s3_moat.STAGE_NAME, 4: s4_capital.STAGE_NAME,
        5: s5_owner_earnings.STAGE_NAME, 6: s6_valuation.STAGE_NAME,
        7: s7_safety.STAGE_NAME, 8: s8_inversion.STAGE_NAME,
    }
    return StageResult(
        stage_id=stage_id,
        stage_name=name_map.get(stage_id, f"Stage {stage_id}"),
        verdict=Verdict.SKIP,
        findings=[f"⊘ {reason_cn}"],
        raw_data={"skipped": True, "skip_reason": reason_cn},
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


def _plan_stages(
    all_ids: Iterable[int],
    only_stages: list[int] | None,
    from_stage: int | None,
    skip_claude: bool,
    done_ids: set[int],
) -> tuple[set[int], set[int]]:
    """
    Given knobs, return (to_run, to_skip_synthetically). `to_run` are stage ids we
    actually execute; `to_skip_synthetically` get a SKIP result appended so the
    report still has 8 stages (for diff + verdict logic).
    """
    all_ids = set(all_ids)
    to_run: set[int] = set()
    to_skip: set[int] = set()
    for sid in all_ids:
        if sid in done_ids:
            continue
        # Filter by only_stages
        if only_stages is not None and sid not in only_stages:
            to_skip.add(sid)
            continue
        # Filter by from_stage
        if from_stage is not None and sid < from_stage:
            to_skip.add(sid)
            continue
        # Filter by skip_claude
        if skip_claude and sid in CLAUDE_STAGE_IDS:
            to_skip.add(sid)
            continue
        to_run.add(sid)
    return to_run, to_skip


def _skip_reason(sid: int, only_stages, from_stage, skip_claude) -> str:
    if only_stages is not None and sid not in only_stages:
        return f"--only {sorted(only_stages)}"
    if from_stage is not None and sid < from_stage:
        return f"--from {from_stage}"
    if skip_claude and sid in CLAUDE_STAGE_IDS:
        return "--no-claude"
    return "skipped"


def run_audit_auto(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
    progress_callback: Callable[[int, StageResult], None] | None = None,
    resume_from: AuditReport | None = None,
    skip_claude: bool = False,
    only_stages: list[int] | None = None,
    from_stage: int | None = None,
    my_market_expectation: str = "",
    my_variant_view: str = "",
) -> AuditReport:
    report = resume_from or _new_report(
        ticker, anchor_thesis,
        my_market_expectation=my_market_expectation,
        my_variant_view=my_variant_view,
    )
    if resume_from and my_variant_view and not report.my_variant_view:
        report.my_variant_view = my_variant_view
    if resume_from and my_market_expectation and not report.my_market_expectation:
        report.my_market_expectation = my_market_expectation

    done_ids = {s.stage_id for s in report.stages if s.verdict != Verdict.SKIP}
    prior = {s.stage_id: s.raw_data for s in report.stages}

    effective_variant = my_variant_view or report.my_variant_view

    all_ids = [sid for sid, _ in STAGES]
    to_run, to_skip = _plan_stages(all_ids, only_stages, from_stage, skip_claude, done_ids)

    for sid, fn in STAGES:
        if sid in done_ids:
            continue
        if sid in to_skip:
            reason = _skip_reason(sid, only_stages, from_stage, skip_claude)
            result = _skipped(sid, reason)
        elif sid in to_run:
            result = _run_stage_safe(
                sid, fn, cfg, keys, ticker, tech_mode, prior, anchor_thesis,
                my_variant_view=effective_variant,
            )
        else:
            continue

        # Replace any previous SKIP record for this stage (so resume + re-run works)
        report.stages = [s for s in report.stages if s.stage_id != sid]
        report.stages.append(result)
        _track_cost(report, result)
        prior[sid] = result.raw_data
        if progress_callback:
            progress_callback(sid, result)

    # Sort stages in canonical order for reproducibility
    report.stages.sort(key=lambda s: s.stage_id)
    return _finalize(report)


def run_audit_wizard(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str = "",
    tech_mode: bool = False,
    resume_from: AuditReport | None = None,
    skip_claude: bool = False,
    only_stages: list[int] | None = None,
    from_stage: int | None = None,
    my_market_expectation: str = "",
    my_variant_view: str = "",
) -> Generator[tuple[int, StageResult, AuditReport], bool, AuditReport]:
    report = resume_from or _new_report(
        ticker, anchor_thesis,
        my_market_expectation=my_market_expectation,
        my_variant_view=my_variant_view,
    )
    done_ids = {s.stage_id for s in report.stages if s.verdict != Verdict.SKIP}
    prior = {s.stage_id: s.raw_data for s in report.stages}

    effective_variant = my_variant_view or report.my_variant_view

    all_ids = [sid for sid, _ in STAGES]
    to_run, to_skip = _plan_stages(all_ids, only_stages, from_stage, skip_claude, done_ids)

    for sid, fn in STAGES:
        if sid in done_ids:
            continue
        if sid in to_skip:
            reason = _skip_reason(sid, only_stages, from_stage, skip_claude)
            result = _skipped(sid, reason)
        elif sid in to_run:
            result = _run_stage_safe(
                sid, fn, cfg, keys, ticker, tech_mode, prior, anchor_thesis,
                my_variant_view=effective_variant,
            )
        else:
            continue

        report.stages = [s for s in report.stages if s.stage_id != sid]
        report.stages.append(result)
        _track_cost(report, result)
        prior[sid] = result.raw_data
        cont = yield sid, result, report
        if cont is False:
            report.stages.sort(key=lambda s: s.stage_id)
            return report

    report.stages.sort(key=lambda s: s.stage_id)
    return _finalize(report)
