"""
Tests for the orchestrator's iteration-speed knobs:
- skip_claude: stages 3/4/8 SKIP without calling Claude
- only_stages: run exactly the listed stage ids
- from_stage:  run stage N onwards
- resume_from: continue from a partial AuditReport

All tests monkeypatch every stage's run() to a deterministic stub so we never
hit the network and run in milliseconds.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine import orchestrator
from engine.models import AuditReport, Metric, StageResult, Verdict
from engine.orchestrator import run_audit_auto
from shared.config import ApiKeys, Config


@pytest.fixture
def tmp_cfg(tmp_path) -> Config:
    data = tmp_path / "data"
    data.mkdir()
    return Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


@pytest.fixture
def keys() -> ApiKeys:
    return ApiKeys(
        anthropic="sk-ant-test", perplexity="pplx-test",
        financial_datasets="fd-test", fred="",
    )


@pytest.fixture(autouse=True)
def stub_all_stages(monkeypatch):
    """Replace every stage's run() + the company-info fetch with a stub."""

    def fake_company_info(ticker):
        return {"long_name": f"{ticker} Corp"}

    monkeypatch.setattr(
        "engine.providers.yfinance_provider.fetch_company_info", fake_company_info,
    )

    # Each stage's run returns a PASS with one metric indicating it ran.
    def make_stub(stage_id, name):
        def _run(*args, **kwargs):
            raw = {"cost_usd": 0.1 if stage_id in (3, 4, 8) else 0.0}
            # Populate signals representative of real output so the Stage 8
            # gate sees enough useful data.
            if stage_id in (3, 4):
                raw["claude_parsed"] = {"summary_cn": "stub"}
            if stage_id == 6:
                raw["valuation"] = {"base_iv": 100, "current_price": 80}
                raw["base_iv"] = 100
            if stage_id == 7:
                raw["margin_of_safety_pct"] = 40
                raw["current_price"] = 80
                raw["target_buy"] = 70
                raw["target_sell"] = 110
            return StageResult(
                stage_id=stage_id, stage_name=name,
                verdict=Verdict.PASS,
                metrics=[Metric(
                    name=f"s{stage_id}_ran", value=1.0,
                    threshold=">= 1", **{"pass": True},
                )],
                findings=[f"stub stage {stage_id}"],
                raw_data=raw,
            )
        return _run

    import engine.stages as pkg
    for sid, mod_name in [
        (1, "s1_competence"), (2, "s2_integrity"),
        (3, "s3_moat"), (4, "s4_capital"),
        (5, "s5_owner_earnings"), (6, "s6_valuation"),
        (7, "s7_safety"), (8, "s8_inversion"),
    ]:
        mod = getattr(pkg, mod_name)
        monkeypatch.setattr(mod, "run", make_stub(sid, mod.STAGE_NAME))


# =========================================================================
# skip_claude
# =========================================================================

def test_skip_claude_marks_stages_3_4_8_as_skip(tmp_cfg, keys):
    report = run_audit_auto(tmp_cfg, keys, "AAPL", skip_claude=True)
    by_id = {s.stage_id: s for s in report.stages}
    for sid in (3, 4, 8):
        assert by_id[sid].verdict == Verdict.SKIP
        assert any("no-claude" in f for f in by_id[sid].findings)
    # Non-Claude stages ran normally
    for sid in (1, 2, 5, 6, 7):
        assert by_id[sid].verdict == Verdict.PASS


def test_skip_claude_has_zero_cost(tmp_cfg, keys):
    report = run_audit_auto(tmp_cfg, keys, "AAPL", skip_claude=True)
    # Stages 3/4/8 each cost $0.10 in the stub. With skip_claude all three skipped.
    assert report.total_api_cost_usd == pytest.approx(0.0)


# =========================================================================
# only_stages
# =========================================================================

def test_only_stages_runs_just_listed_ids(tmp_cfg, keys):
    report = run_audit_auto(tmp_cfg, keys, "AAPL", only_stages=[6])
    by_id = {s.stage_id: s for s in report.stages}
    # All 8 stages are present in the report (as SKIP placeholders or real)
    assert set(by_id) == set(range(1, 9))
    assert by_id[6].verdict == Verdict.PASS
    for sid in [1, 2, 3, 4, 5, 7, 8]:
        assert by_id[sid].verdict == Verdict.SKIP


def test_only_stages_multiple(tmp_cfg, keys):
    report = run_audit_auto(tmp_cfg, keys, "AAPL", only_stages=[5, 6, 7])
    by_id = {s.stage_id: s for s in report.stages}
    for sid in (5, 6, 7):
        assert by_id[sid].verdict == Verdict.PASS
    for sid in (1, 2, 3, 4, 8):
        assert by_id[sid].verdict == Verdict.SKIP


# =========================================================================
# from_stage
# =========================================================================

def test_from_stage_skips_earlier(tmp_cfg, keys):
    report = run_audit_auto(tmp_cfg, keys, "AAPL", from_stage=5)
    by_id = {s.stage_id: s for s in report.stages}
    for sid in (1, 2, 3, 4):
        assert by_id[sid].verdict == Verdict.SKIP
    for sid in (5, 6, 7, 8):
        assert by_id[sid].verdict == Verdict.PASS


# =========================================================================
# resume_from
# =========================================================================

def test_resume_keeps_already_done_stages(tmp_cfg, keys):
    first = run_audit_auto(tmp_cfg, keys, "AAPL")
    assert all(s.verdict == Verdict.PASS for s in first.stages)
    original_cost = first.total_api_cost_usd

    # Simulate "I want to only re-run Stage 6 on this exact report"
    resumed = run_audit_auto(tmp_cfg, keys, "AAPL",
                             resume_from=first, only_stages=[6])
    by_id = {s.stage_id: s for s in resumed.stages}
    # Stage 6 re-ran; others kept their original PASS status (not marked SKIP)
    assert by_id[6].verdict == Verdict.PASS
    for sid in (1, 2, 3, 4, 5, 7, 8):
        assert by_id[sid].verdict == Verdict.PASS


# =========================================================================
# Stage 8 gating (integration)
# =========================================================================

def test_stage8_skips_when_priors_insufficient(tmp_cfg, keys, monkeypatch):
    """If stages 3/4/6/7 all fail/skip, Stage 8 should gate itself off."""
    # Override stages 3/4/6/7 to return SKIPs with no useful raw_data.
    import engine.stages as pkg
    for mod_name in ("s3_moat", "s4_capital", "s6_valuation", "s7_safety"):
        mod = getattr(pkg, mod_name)
        def _skip(*a, _n=mod.STAGE_NAME, _i=mod.STAGE_ID, **kw):
            return StageResult(stage_id=_i, stage_name=_n, verdict=Verdict.SKIP,
                               findings=["stubbed failure"], raw_data={})
        monkeypatch.setattr(mod, "run", _skip)

    report = run_audit_auto(tmp_cfg, keys, "AAPL")
    s8 = next(s for s in report.stages if s.stage_id == 8)
    assert s8.verdict == Verdict.SKIP
    assert s8.raw_data.get("skipped_reason") == "insufficient_prior_signals"


# =========================================================================
# my_variant_view plumbing
# =========================================================================

def test_variant_view_persists_into_report(tmp_cfg, keys):
    text = "我认为市场低估了 AI 时代护城河加深"
    report = run_audit_auto(
        tmp_cfg, keys, "AAPL",
        my_market_expectation="市场 price in 20% 增长",
        my_variant_view=text,
    )
    assert report.my_variant_view == text
    assert "20%" in report.my_market_expectation
