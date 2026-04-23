"""Stage-specific Munger prompt regression tests (P1-7)."""

from __future__ import annotations

from engine.coach import _GENERIC_PROMPT, _STAGE_PROMPTS, _rule_template
from engine.models import StageResult, Verdict


def _make(stage_id: int, verdict: Verdict) -> StageResult:
    return StageResult(
        stage_id=stage_id,
        stage_name=f"Stage{stage_id}",
        verdict=verdict,
        metrics=[],
        findings=[],
    )


def test_stage_prompts_exist_for_all_8_stages_and_3_verdicts():
    # 每个 stage × (PASS/FAIL/BORDERLINE) 都必须有定制 prompt
    for stage_id in range(1, 9):
        for v in ("PASS", "FAIL", "BORDERLINE"):
            assert (stage_id, v) in _STAGE_PROMPTS, f"missing prompt for stage {stage_id}/{v}"


def test_stage_prompts_are_not_the_generic_one():
    for key, text in _STAGE_PROMPTS.items():
        assert (
            text != _GENERIC_PROMPT
        ), f"stage {key} is using the generic prompt, defeat the purpose"
        assert len(text) > 20


def test_rule_template_uses_stage_specific_for_s1_fail():
    r = _rule_template(_make(1, Verdict.FAIL), quote=None)
    # stage 1 FAIL 的具体提示
    assert "不懂" in r or "不敢" in r
    assert "如果这个判断是错的" not in r  # shouldn't fall back to generic


def test_rule_template_uses_stage_specific_for_s7_fail():
    r = _rule_template(_make(7, Verdict.FAIL), quote=None)
    assert "溢价" in r or "乐观" in r
    assert "非共识" in r


def test_rule_template_falls_back_to_generic_for_unknown_verdict():
    # SKIP has no stage-specific prompt → should fall back to generic
    r = _rule_template(_make(3, Verdict.SKIP), quote=None)
    assert _GENERIC_PROMPT in r
