"""Guardrails for Claude JSON outputs."""

from __future__ import annotations

from engine.guardrails import (
    _extract_json_blob,
    validate_inversion,
    validate_management,
    validate_moat,
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
    text = (
        '{"integrity_score": 18, "capital_allocation_score": 16, '
        '"shareholder_orientation_score": 17, "buffett_verdict_cn": "值得信任", '
        '"summary_cn": "x"}'
    )
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


# =========================================================================
# R3-6: parse-error logging (post-mortem trail)
# =========================================================================


def test_parse_failure_writes_log_file(tmp_path, monkeypatch):
    """When validation fails, a JSON file lands under
    `<MOATLENS_DATA_DIR>/logs/claude-parse-errors/` with the raw text
    and error list — gives us a forensics trail when sonnet drifts."""
    monkeypatch.setenv("MOATLENS_DATA_DIR", str(tmp_path))

    bad_text = "this is not json at all"
    data, errors = validate_moat(bad_text)
    assert data == {}
    assert errors and "json_parse" in errors[0]

    log_dir = tmp_path / "logs" / "claude-parse-errors"
    assert log_dir.exists()
    files = list(log_dir.glob("*.json"))
    assert len(files) == 1
    import json as _json

    payload = _json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["schema"] == "MoatAnalysis"
    assert payload["raw_text"] == bad_text
    assert payload["errors"] == errors


def test_partial_validation_failure_also_logged(tmp_path, monkeypatch):
    """Even when partial recovery succeeds, the original errors should
    be logged so we can diagnose schema drift over time."""
    monkeypatch.setenv("MOATLENS_DATA_DIR", str(tmp_path))

    # `total_score`: "high" is not coercible to int → ValidationError, partial recovery
    text = '{"total_score": "high", "summary_cn": "ok"}'
    data, errors = validate_moat(text)
    assert errors  # validation captured the bad field

    log_dir = tmp_path / "logs" / "claude-parse-errors"
    files = list(log_dir.glob("*.json"))
    assert len(files) == 1


def test_happy_path_writes_no_log(tmp_path, monkeypatch):
    """Successful parse must not produce a log file (would be noise)."""
    monkeypatch.setenv("MOATLENS_DATA_DIR", str(tmp_path))

    text = '{"total_score": 80, "summary_cn": "good"}'
    data, errors = validate_moat(text)
    assert errors == []

    log_dir = tmp_path / "logs" / "claude-parse-errors"
    assert not log_dir.exists() or list(log_dir.glob("*.json")) == []
