"""
Stage 8: Inversion & Variant View Canvas (Munger lens).

Philosophy: Munger's "Invert, always invert". Most failures come from not
asking "how would this be a disaster?"

Two parts:
1. Failure mode identification — 3+ scenarios where this investment fails
2. Variant View Canvas (9 questions from Howard Marks)

Uses Claude (sonnet-4-5) for deep reasoning.
"""
from __future__ import annotations

import json
import time

from engine.models import StageResult, Verdict
from engine.prompts_loader import load_prompt
from engine.providers import claude as p_claude
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 8
STAGE_NAME = "反方论点 & Variant View"
PROMPT_SLUG = "s8_inversion"


_LEGACY_SYSTEM_PROMPT = """你是一位遵循 Charlie Munger "Invert, always invert" 思维的分析师。你的任务：

1. 列出这个投资**最可能失败**的 3-5 种方式。不要给空泛答案（如 "管理层变坏"），要**具体、可追踪**（如 "OpenAI 和 Google 联合推动 CUDA 的替代开源标准，3 年内开发者生态迁移 50%"）。

2. 回答 Howard Marks 的 Variant View Canvas 9 问：
   1. 未来 5-10 年可能结果区间？（最坏 / 基准 / 最好）
   2. 你认为最可能结果？
   3. 你正确的概率？
   4. 市场当前共识是什么？
   5. 你与共识的差异？
   6. 当前价格反映哪个情景？
   7. 价格情绪偏乐观还是悲观？
   8. 若市场对，价格如何变？
   9. 若你对，价格如何变？

严格按 JSON 格式输出：

```json
{
  "failure_modes": [
    {
      "scenario": "具体描述",
      "probability_pct": 15,
      "early_signals": ["..."],
      "impact_on_thesis": "彻底否定 | 部分削弱 | 微弱"
    }
  ],
  "variant_view": {
    "range_worst": "...",
    "range_base": "...",
    "range_best": "...",
    "most_likely_outcome": "...",
    "my_correctness_probability_pct": 55,
    "market_consensus": "...",
    "my_difference": "...",
    "price_reflects_scenario": "最坏 | 基准 | 最好",
    "price_sentiment": "乐观 | 悲观 | 中性",
    "if_market_right": "...",
    "if_i_right": "..."
  },
  "munger_inversion_summary": "200 字中文总结"
}
```
"""


def run(
    cfg: Config, keys: ApiKeys, ticker: str,
    anchor_thesis: str,
    prior_stages_summary: dict,
    my_variant_view: str = "",
) -> StageResult:
    t0 = time.time()

    try:
        system_prompt, prompt_version = load_prompt(cfg, PROMPT_SLUG)
    except FileNotFoundError:
        system_prompt, prompt_version = _LEGACY_SYSTEM_PROMPT, "inline-fallback"

    variant_block = (
        f"\n\n# 用户的非共识观点 (my variant view)\n{my_variant_view}\n"
        "在 variant_view.my_difference 中必须**明确引用或评估**用户这段话，并在"
        "if_i_right 中说明若用户这个差异是正确的，未来 3 年价格会怎么演化。"
    ) if my_variant_view else ""

    user_prompt = f"""# 审视对象
Ticker: {ticker}

# 用户初始论点
{anchor_thesis or "(未提供)"}
{variant_block}
# 前面 7 阶段的判断摘要

## Stage 3 护城河（摘要）
{json.dumps(prior_stages_summary.get('stage3', {}), ensure_ascii=False, indent=2)[:2000]}

## Stage 4 管理层（摘要）
{json.dumps(prior_stages_summary.get('stage4', {}), ensure_ascii=False, indent=2)[:1500]}

## Stage 6 估值（摘要）
{json.dumps(prior_stages_summary.get('stage6', {}), ensure_ascii=False, indent=2)[:1500]}

## Stage 7 安全边际（摘要）
{json.dumps(prior_stages_summary.get('stage7', {}), ensure_ascii=False, indent=2)[:1500]}

请严格按系统提示词的 JSON 格式输出。"""

    claude_output, cost = p_claude.analyze(
        cfg, keys, system_prompt, user_prompt, max_tokens=3500,
    )

    from engine.guardrails import validate_inversion
    parsed, parse_errors = validate_inversion(claude_output)
    if parse_errors:
        parsed["parse_errors"] = parse_errors
    if not parsed.get("munger_inversion_summary"):
        parsed["munger_inversion_summary"] = claude_output[:500]

    metrics = []
    findings = []

    failure_modes = parsed.get("failure_modes", [])
    metrics.append(make_metric(
        "失败模式数量", len(failure_modes),
        "≥ 3", len(failure_modes) >= 3,
        note="越多越好 — 证明你真正想过'怎么会错'",
    ))

    # Total failure probability
    total_failure_prob = sum(f.get("probability_pct", 0) for f in failure_modes)
    metrics.append(make_metric(
        "总失败概率", total_failure_prob,
        "≤ 50% (否则不该买)", total_failure_prob <= 50, unit="%",
        note="若 >50% 失败概率，该投资期望值可能为负",
    ))

    variant = parsed.get("variant_view", {})
    my_correctness = variant.get("my_correctness_probability_pct", 0)
    metrics.append(make_metric(
        "我正确的概率 (自估)", my_correctness,
        "30-70% (过于自信是红旗)",
        30 <= my_correctness <= 70, unit="%",
        note="> 70% 是过度自信；< 30% 则不该下注",
    ))

    # Findings
    findings.append("## 🔄 失败模式 (Munger Inversion)")
    for i, fm in enumerate(failure_modes, 1):
        findings.append(
            f"{i}. **{fm.get('scenario', '?')}** "
            f"(概率 {fm.get('probability_pct', '?')}%, "
            f"影响: {fm.get('impact_on_thesis', '?')})"
        )
        signals = fm.get("early_signals", [])
        if signals:
            findings.append(f"   早期信号: {'; '.join(signals[:3])}")

    findings.append("")
    findings.append("## 🎯 Variant View Canvas")
    if variant:
        findings.append(f"- 可能结果区间: {variant.get('range_worst', '?')} / {variant.get('range_base', '?')} / {variant.get('range_best', '?')}")
        findings.append(f"- 最可能: {variant.get('most_likely_outcome', '?')}")
        findings.append(f"- 市场共识: {variant.get('market_consensus', '?')}")
        findings.append(f"- 我的差异: {variant.get('my_difference', '?')}")
        findings.append(f"- 价格反映情景: {variant.get('price_reflects_scenario', '?')}")
        findings.append(f"- 情绪偏好: {variant.get('price_sentiment', '?')}")
        findings.append(f"- 若市场对: {variant.get('if_market_right', '?')}")
        findings.append(f"- 若我对: {variant.get('if_i_right', '?')}")

    if parsed.get("munger_inversion_summary"):
        findings.append("")
        findings.append("## 💭 芒格式总结")
        findings.append(parsed["munger_inversion_summary"])

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "claude_parsed": parsed,
            "failure_modes": failure_modes,
            "variant_view": variant,
            "cost_usd": cost,
            "prompt_slug": PROMPT_SLUG,
            "prompt_version": prompt_version,
        },
        elapsed_seconds=time.time() - t0,
    )
