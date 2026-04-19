"""Guardrails for Claude JSON outputs."""
from __future__ import annotations

from engine.guardrails import (
    _extract_json_blob, parse_claude_json,
    MoatAnalysis, ManagementAnalysis, InversionAnalysis,
    validate_moat, validate_management, validate_inversion,
)


def test_extract_json_from_fenced():
    t = 'prose\n```json\n{"total_score": 78, "munger_verdict": "wonderful"}\n```\nmore prose'
    out = _extract_json_blob(t)
    assert '"total_score": 78' in out


def test_extract_json_from_bare():
    t = 'prose\n{"a": 1}\n'
    out = _extract_json_blob(t)
    assert out == '{"a": 1}'


def test_moat_happy_path():
    text = """```json
    {"total_score": 78, "moat_scores": {"brand": 18},
     "strongest_moats": ["brand"],
     "lollapalooza": true, "business_model_score": 9,
     "summary_cn": "hello", "munger_verdict": "wonderful"}
    ```"""
    data, errors = validate_moat(text)
    assert errors == []
    assert data["total_score"] == 78
    assert data["munger_verdict"] == "wonderful"
    assert data["lollapalooza"] is True


def test_moat_recovers_from_bad_field():
    """Claude returns '强' as string for total_score (int). We keep other fields."""
    text = '{"total_score": "强", "munger_verdict": "wonderful", "summary_cn": "x"}'
    data, errors = validate_moat(text)
    assert errors  # flagged
    assert data.get("munger_verdict") == "wonderful"


def test_moat_clamps_out_of_range():
    """total_score 150 violates ge=0, le=100."""
    text = '{"total_score": 150, "summary_cn": "x"}'
    data, errors = validate_moat(text)
    assert errors
    # After partial recovery, the invalid field may be absent or defaulted
    assert data.get("summary_cn") == "x"


def test_moat_completely_garbage_returns_empty():
    data, errors = validate_moat("NOT JSON AT ALL")
    assert errors
    assert data == {} or data == {"summary_cn": ""}


def test_management_happy_path():
    text = '{"integrity_score": 18, "capital_allocation_score": 16, ' \
           '"shareholder_orientation_score": 17, "buffett_verdict_cn": "值得信任", ' \
           '"summary_cn": "x"}'
    data, errors = validate_management(text)
    assert errors == []
    assert data["integrity_score"] == 18


def test_inversion_happy_path():
    text = """{"failure_modes": [{"scenario": "A", "probability_pct": 15,
               "early_signals": ["x"], "impact_on_thesis": "彻底否定"}],
               "variant_view": {"my_correctness_probability_pct": 55},
               "munger_inversion_summary": "x"}"""
    data, errors = validate_inversion(text)
    assert errors == []
    assert len(data["failure_modes"]) == 1
    assert data["failure_modes"][0]["probability_pct"] == 15


def test_inversion_invalid_fm_probability():
    text = '{"failure_modes": [{"scenario": "A", "probability_pct": 500}]}'
    data, errors = validate_inversion(text)
    assert errors  # 500 > 100 — invalid
