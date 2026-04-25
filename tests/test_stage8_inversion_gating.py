"""
Tests for Stage 8 orchestrator-level gating.

Stage 8 (Munger inversion) is expensive ($0.2-0.4 per call to sonnet-4-5).
The orchestrator gates it: if fewer than 2 of stages 3/4/6/7 produced
useful data, skip Claude — otherwise we pay for hallucinated failure modes.

These tests lock the gating contract without invoking Claude.
"""

from __future__ import annotations

from unittest.mock import patch

from engine.models import Verdict
from engine.orchestrator import _stage8


class _Stub:
    pass


# =========================================================================
# Gating: useful < 2 → SKIP without Claude call
# =========================================================================


def test_stage8_skips_when_no_prior_signals():
    """Empty prior → no useful signals → SKIP, no Claude spend."""
    result = _stage8(_Stub(), _Stub(), "AAPL", tech_mode=False, prior={})
    assert result.verdict == Verdict.SKIP
    assert "insufficient_prior_signals" in result.raw_data.get("skipped_reason", "")


def test_stage8_skips_when_prior_has_only_one_useful_stage():
    """Single useful stage < threshold of 2 → still SKIP."""
    prior = {
        3: {"claude_parsed": {"total_score": 60}},  # 1 useful
        4: {"error": True},  # marked errored
        6: {},  # empty
        7: {},  # empty
    }
    result = _stage8(_Stub(), _Stub(), "AAPL", tech_mode=False, prior=prior)
    assert result.verdict == Verdict.SKIP


def test_stage8_counts_error_as_not_useful():
    """raw.get("error") truthy → that stage doesn't contribute to useful count."""
    prior = {
        3: {"error": True, "claude_parsed": {"total_score": 90}},  # erro + parsed → not useful
        4: {"error": True},
    }
    result = _stage8(_Stub(), _Stub(), "AAPL", tech_mode=False, prior=prior)
    assert result.verdict == Verdict.SKIP


# =========================================================================
# Gating: useful >= 2 → Claude call proceeds (mocked)
# =========================================================================


def test_stage8_proceeds_when_two_useful_stages():
    """s6 valuation dict + s7 MOS pct = 2 useful → should call s8_inversion.run.
    We patch it out to avoid hitting Claude in test."""
    prior = {
        3: {},
        4: {},
        6: {"valuation": {"current_price": 100}},  # has 'valuation' → useful
        7: {"margin_of_safety_pct": 15.0},  # has MOS → useful
    }
    with patch("engine.orchestrator.s8_inversion.run") as mock_run:
        # Mock return — any StageResult-shaped value; we only care the call happened
        from engine.models import StageResult

        mock_run.return_value = StageResult(
            stage_id=8,
            stage_name="mock",
            verdict=Verdict.PASS,
            findings=[],
            metrics=[],
            raw_data={},
        )
        result = _stage8(
            _Stub(),
            _Stub(),
            "AAPL",
            tech_mode=False,
            prior=prior,
            anchor_thesis="",
            my_variant_view="",
        )
        mock_run.assert_called_once()
        assert result.verdict == Verdict.PASS


def test_stage8_counts_claude_parsed_as_useful():
    """raw.get('claude_parsed') non-empty → useful (covers stages 3/4)."""
    prior = {
        3: {"claude_parsed": {"total_score": 70}},
        4: {"claude_parsed": {"integrity_score": 15}},
        6: {},
        7: {},
    }
    with patch("engine.orchestrator.s8_inversion.run") as mock_run:
        from engine.models import StageResult

        mock_run.return_value = StageResult(
            stage_id=8,
            stage_name="mock",
            verdict=Verdict.PASS,
            findings=[],
            metrics=[],
            raw_data={},
        )
        _stage8(
            _Stub(),
            _Stub(),
            "AAPL",
            tech_mode=False,
            prior=prior,
            anchor_thesis="",
            my_variant_view="",
        )
        mock_run.assert_called_once()
