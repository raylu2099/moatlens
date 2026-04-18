"""
Integration tests for filesystem storage + audit diff.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from engine.models import (
    Action, AuditReport, ConfidenceLevel, Metric, StageResult, Verdict,
)
from shared.config import Config
from shared.storage import (
    list_audits, load_audit, load_last_two_audits, save_audit,
)
from web.diff import compute_diff, render_audit_diff_html, render_audit_diff_text


@pytest.fixture
def tmp_cfg(tmp_path) -> Config:
    """A Config pointing at tmp_path for isolation."""
    data = tmp_path / "data"
    cache = data / "cache"
    data.mkdir()
    cache.mkdir()
    return Config(
        data_dir=data,
        cache_dir=cache,
        prompts_dir=tmp_path / "prompts",
        docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60,
        cache_perplexity_ttl=60,
        cache_macro_ttl=60,
        project_root=tmp_path,
    )


def _make_report(ticker: str, date: str, stage_values: dict[int, tuple[Verdict, float]]) -> AuditReport:
    """Build a minimal but diff-able report."""
    stages = []
    for sid in sorted(stage_values):
        verdict, metric_val = stage_values[sid]
        m = Metric(
            name=f"metric_for_s{sid}", value=metric_val,
            threshold=">=0", **{"pass": verdict == Verdict.PASS},
        )
        stages.append(StageResult(
            stage_id=sid, stage_name=f"stage {sid}",
            verdict=verdict, metrics=[m], findings=[],
            raw_data={"cost_usd": 0.01 * sid},
        ))
    return AuditReport(
        ticker=ticker,
        company_name=f"{ticker} Corp",
        audit_date=date,
        generated_at=datetime.fromisoformat(f"{date}T12:00:00"),
        stages=stages,
        overall_action=Action.WATCH,
        overall_confidence=ConfidenceLevel.MEDIUM,
        total_api_cost_usd=sum(0.01 * sid for sid in stage_values),
    )


# =========================================================================
# Storage roundtrip
# =========================================================================

def test_save_and_load_roundtrip(tmp_cfg):
    report = _make_report("AAPL", "2026-04-10", {1: (Verdict.PASS, 67.0), 2: (Verdict.PASS, 3.5)})
    md_path, json_path = save_audit(tmp_cfg, report, "# Report\nhello")

    assert md_path.exists()
    assert json_path.exists()
    assert md_path.read_text(encoding="utf-8") == "# Report\nhello"

    loaded = load_audit(tmp_cfg, "AAPL", "2026-04-10")
    assert loaded is not None
    assert loaded.ticker == "AAPL"
    assert len(loaded.stages) == 2
    assert loaded.stages[0].verdict == Verdict.PASS


def test_load_audit_missing_returns_none(tmp_cfg):
    assert load_audit(tmp_cfg, "NVDA", "2020-01-01") is None


def test_list_audits_sorts_newest_first(tmp_cfg):
    r_old = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    r_mid = _make_report("AAPL", "2026-02-10", {1: (Verdict.FAIL, 2.0)})
    r_new = _make_report("NVDA", "2026-03-10", {1: (Verdict.PASS, 3.0)})
    for r in [r_old, r_mid, r_new]:
        save_audit(tmp_cfg, r, f"md for {r.ticker} {r.audit_date}")

    listing = list_audits(tmp_cfg)
    assert [a["audit_date"] for a in listing] == ["2026-03-10", "2026-02-10", "2026-01-10"]
    assert listing[0]["action"] == "WATCH"
    assert listing[0]["total_cost_usd"] == pytest.approx(0.01)


def test_load_last_two_audits(tmp_cfg):
    r_old = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    r_new = _make_report("AAPL", "2026-04-10", {1: (Verdict.FAIL, 0.5)})
    save_audit(tmp_cfg, r_old, "old")
    save_audit(tmp_cfg, r_new, "new")

    current, previous = load_last_two_audits(tmp_cfg, "AAPL")
    assert current is not None and previous is not None
    assert current.audit_date == "2026-04-10"
    assert previous.audit_date == "2026-01-10"


def test_load_last_two_when_only_one(tmp_cfg):
    r = _make_report("AAPL", "2026-04-10", {1: (Verdict.PASS, 1.0)})
    save_audit(tmp_cfg, r, "only")
    current, previous = load_last_two_audits(tmp_cfg, "AAPL")
    assert current is not None
    assert previous is None


def test_load_last_two_when_none(tmp_cfg):
    current, previous = load_last_two_audits(tmp_cfg, "NOPE")
    assert current is None and previous is None


# =========================================================================
# Diff
# =========================================================================

def test_diff_detects_verdict_change():
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.FAIL, 0.5)})

    d = compute_diff(curr, prev)
    assert d["ticker"] == "AAPL"
    assert d["current_date"] == "2026-04-10"
    assert d["previous_date"] == "2026-01-10"
    s1 = next(s for s in d["stages"] if s["stage_id"] == 1)
    assert s1["verdict_from"] == "PASS"
    assert s1["verdict_to"] == "FAIL"
    assert s1["verdict_arrow"] == "↓"


def test_diff_detects_metric_value_change():
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.PASS, 2.0)})

    d = compute_diff(curr, prev)
    s1 = next(s for s in d["stages"] if s["stage_id"] == 1)
    assert len(s1["metric_changes"]) == 1
    assert s1["metric_changes"][0]["from"] == 1.0
    assert s1["metric_changes"][0]["to"] == 2.0


def test_diff_marks_stage_only_in_one_side():
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0), 2: (Verdict.PASS, 1.0)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.PASS, 1.0)})  # stage 2 dropped

    d = compute_diff(curr, prev)
    s2 = next(s for s in d["stages"] if s["stage_id"] == 2)
    assert s2.get("only_in") == "previous"


def test_diff_upward_verdict_arrow():
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.FAIL, 0.5)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.PASS, 2.0)})
    d = compute_diff(curr, prev)
    s1 = next(s for s in d["stages"] if s["stage_id"] == 1)
    assert s1["verdict_arrow"] == "↑"


def test_diff_text_renderer_runs_without_error():
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.FAIL, 0.5)})
    out = render_audit_diff_text(curr, prev)
    assert "AAPL" in out
    assert "2026-01-10" in out
    assert "2026-04-10" in out
    assert "PASS" in out and "FAIL" in out


def test_diff_html_renderer_escapes_input():
    """HTML renderer must escape to avoid injection even though this is local."""
    prev = _make_report("AAPL", "2026-01-10", {1: (Verdict.PASS, 1.0)})
    curr = _make_report("AAPL", "2026-04-10", {1: (Verdict.FAIL, 0.5)})
    curr.stages[0].stage_name = "<script>alert(1)</script>"

    html = render_audit_diff_html(curr, prev)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
