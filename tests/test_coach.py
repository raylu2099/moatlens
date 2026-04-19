"""Coach commentary tests — mocked Haiku, no network."""
from __future__ import annotations

import pytest

from engine.coach import _rule_template, commentary
from engine.models import Metric, StageResult, Verdict
from engine.wisdom import Quote
from shared.config import ApiKeys, Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        data_dir=tmp_path, cache_dir=tmp_path / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="", pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


@pytest.fixture
def keys() -> ApiKeys:
    return ApiKeys(anthropic="sk-ant-test")


@pytest.fixture
def stage_pass() -> StageResult:
    return StageResult(
        stage_id=1, stage_name="能力圈 & 垃圾桶",
        verdict=Verdict.PASS,
        metrics=[
            Metric(name="ROIC (5Y avg)", value=62.0, unit="%",
                   threshold="> 15%", **{"pass": True}),
            Metric(name="Gross Margin", value=44.0, unit="%",
                   threshold="> 40%", **{"pass": True}),
        ],
        findings=["Apple 是 Buffett 愿意认真看的那种公司。"],
        raw_data={},
    )


@pytest.fixture
def quote() -> Quote:
    return Quote(
        id="buffett_circle_edge_size",
        author="Warren Buffett",
        text_en="Knowing the edge of your circle of competence...",
        text_cn="知道能力圈的边界，比能力圈本身的大小重要得多。",
        source="Berkshire 1996 致股东的信",
        themes=["competence", "humility"], stages=[1], triggers=[],
    )


# =====================================================================
# Rule-mode fallback
# =====================================================================

def test_rule_mode_includes_quote(cfg, keys, stage_pass, quote):
    out = commentary(cfg, keys, stage_pass, quote, mode="rule")
    assert "能力圈的边界" in out                # Chinese quote
    assert "Warren Buffett" in out             # Attribution
    assert "Berkshire 1996" in out             # Source
    assert "Stage 1" in out
    assert "通过" in out                        # verdict translated
    assert "问自己" in out                      # Munger-style closer


def test_rule_mode_without_quote(cfg, keys, stage_pass):
    out = commentary(cfg, keys, stage_pass, quote=None, mode="rule")
    assert "Stage 1" in out
    assert "能力圈的边界" not in out
    # Still gets the Munger question
    assert "问自己" in out


def test_rule_mode_with_fail_verdict(cfg, keys, quote):
    stage_fail = StageResult(
        stage_id=2, stage_name="诚实度测谎",
        verdict=Verdict.FAIL,
        metrics=[Metric(name="OCF/NI", value=0.4, unit="x",
                        threshold="> 1.0", **{"pass": False})],
    )
    out = commentary(cfg, keys, stage_fail, quote, mode="rule")
    assert "Stage 2" in out
    assert "不通过" in out


# =====================================================================
# Haiku mode (mocked)
# =====================================================================

def test_haiku_mode_calls_claude_and_returns_text(
    cfg, keys, stage_pass, quote, monkeypatch,
):
    called_with = {}

    def fake_analyze(cfg_, keys_, system_prompt, user_prompt, **kwargs):
        called_with["system"] = system_prompt
        called_with["user"] = user_prompt
        called_with["model"] = kwargs.get("model")
        # Return plausible coach output
        return (
            "AAPL 的 ROIC 62% 是 Buffett 圈内的优等生。\n\n"
            f"> {quote.text_cn}\n> — {quote.author}，{quote.source}\n\n"
            "**问自己**: 生态锁定是否会被 AI 时代新接口重塑？"
        ), 0.005

    monkeypatch.setattr("engine.coach.p_claude.analyze", fake_analyze)

    out = commentary(cfg, keys, stage_pass, quote, mode="haiku")
    assert called_with["model"] == "claude-haiku-4-5"
    # Our coach system prompt must instruct to not fabricate quotes
    assert "禁止编造" in called_with["system"]
    # Our user prompt must include the exact quote text for grounding
    assert quote.text_cn in called_with["user"]
    # Output must contain the quote
    assert quote.text_cn in out


def test_haiku_falls_back_to_rule_on_error(
    cfg, keys, stage_pass, quote, monkeypatch,
):
    def failing_analyze(*args, **kwargs):
        return "[Claude error: 429 rate limit]", 0.0

    monkeypatch.setattr("engine.coach.p_claude.analyze", failing_analyze)

    out = commentary(cfg, keys, stage_pass, quote, mode="haiku")
    # Should have fallen back to rule template
    assert "问自己" in out
    assert quote.text_cn in out
    assert "Stage 1" in out


def test_missing_api_key_falls_back_to_rule(cfg, stage_pass, quote):
    no_keys = ApiKeys(anthropic="")
    out = commentary(cfg, no_keys, stage_pass, quote, mode="haiku")
    assert quote.text_cn in out
    assert "问自己" in out


def test_env_var_overrides_mode(cfg, keys, stage_pass, quote, monkeypatch):
    """MOATLENS_COACH=rule should prevent Haiku call even with valid keys."""
    def should_not_be_called(*args, **kwargs):
        raise AssertionError("Haiku called but mode should be rule")

    monkeypatch.setattr("engine.coach.p_claude.analyze", should_not_be_called)
    monkeypatch.setenv("MOATLENS_COACH", "rule")

    out = commentary(cfg, keys, stage_pass, quote)
    assert quote.text_cn in out


def test_rule_template_with_skip_verdict(quote):
    stage_skip = StageResult(
        stage_id=8, stage_name="Inversion",
        verdict=Verdict.SKIP, metrics=[], findings=["Insufficient priors"],
    )
    out = _rule_template(stage_skip, quote)
    assert "跳过" in out
