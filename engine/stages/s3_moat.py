"""
Stage 3: Moat Analysis (Claude-driven).

Philosophy: The core of Munger's "The Lens" — you want wonderful businesses,
not fair ones. Identify which of 5 moat types applies and judge durability.

5 moat categories:
1. Brand premium (Apple, Coca-Cola, LVMH)
2. Network effects (Meta, Google, Amazon Marketplace)
3. Switching costs (Microsoft, ServiceNow, Salesforce)
4. Scale/cost advantages (Costco, Walmart, Amazon Logistics)
5. Intangible assets (patents, regulatory licenses, franchises)

Tech stock addition:
- Data flywheel
- Ecosystem lock-in (iOS, Windows, AWS)
- API/developer lock-in
- Platform economics

Also applies Ray's 11 business model quality tests.

This stage invokes Claude (Sonnet) — the most expensive stage but highest value.
"""

from __future__ import annotations

import json
import time

from engine.models import StageResult
from engine.prompts_loader import load_prompt
from engine.providers import claude as p_claude
from engine.providers import perplexity as p_pplx
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._enrichments import (
    fda_pipeline_summary,
    marketaux_sentiment_summary,
    sec_mda_excerpt,
)
from ._helpers import aggregate_verdict, make_metric

STAGE_ID = 3
STAGE_NAME = "护城河深度验证"
PROMPT_SLUG = "s3_moat"


_LEGACY_SYSTEM_PROMPT = """你是一位严格遵循 Charlie Munger 与 Warren Buffett 框架的资深分析师。

你的任务：评估一家上市公司的护城河（competitive moat）深度与持久性。

评估 5 大类护城河，每类 0-20 分（总分 0-100）：

1. 品牌溢价 (Brand) — 能否定价高于同类、消费者心智占位
2. 网络效应 (Network Effects) — 用户越多产品越有价值
3. 转换成本 (Switching Costs) — 客户换成竞品的金钱/时间/心理成本
4. 规模/成本优势 (Scale/Cost) — 单位成本随规模下降
5. 无形资产 (Intangibles) — 专利/品牌法律保护/监管牌照/数据壁垒

对科技公司额外评估：
- 数据飞轮（data → product → users → data）
- 生态锁定（iOS / Windows / AWS）
- API/开发者锁定
- Platform economics（take rate 稳定性）

然后应用 Ray 的 11 条好商业模式测试（打 ✓ 或 ✗）：
1. 产品需求稳定性（5+ 年验证）
2. 无保质期、无库存风险
3. 轻资产（非重资产）
4. 不依赖持续突破性 R&D
5. 无强周期性
6. 礼品属性（提价不敏感）
7. 虚拟产品（无物流成本）
8. 非零售（有差异化空间）
9. 产品聚焦
10. 低维持性 Capex
11. 高消费频次

最后给出：
- 总分 (0-100)
- 最强 1-2 类护城河 + 证据
- 最弱环节
- 科技公司：AI 时代护城河在**加深**还是**变浅**？举具体例子
- 芒格 "Lollapalooza" 检查：是否多个优势叠加？

严格按以下 JSON 格式输出，不要任何前后文字：

```json
{
  "total_score": 78,
  "moat_scores": {
    "brand": 18,
    "network_effects": 15,
    "switching_costs": 20,
    "scale": 12,
    "intangibles": 13
  },
  "strongest_moats": ["switching_costs", "brand"],
  "strongest_evidence": "具体事实/数据",
  "weakest_link": "...",
  "tech_moat_trend": "strengthening | stable | weakening | n/a",
  "tech_moat_evidence": "...",
  "lollapalooza": true,
  "business_model_checks": {
    "need_stability": true,
    "no_expiry": true,
    "asset_light": true,
    "low_rd_dependency": false,
    "no_cyclicality": true,
    "gift_attribute": false,
    "virtual_product": true,
    "non_retail": true,
    "focused": true,
    "low_maintenance_capex": true,
    "high_frequency": true
  },
  "business_model_score": 9,
  "summary_cn": "一段中文总结（200 字以内）",
  "munger_verdict": "wonderful | fair | avoid"
}
```
"""


def run(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    stage1_raw: dict,
    tech_mode: bool = False,
) -> StageResult:
    t0 = time.time()

    company = yfp.fetch_company_info(ticker)
    company_name = company.get("long_name", ticker)
    sector = company.get("sector", "")
    industry = company.get("industry", "")
    biz_summary = company.get("business_summary", "")

    # Load externalized prompt (falls back to legacy inline copy on filesystem issues).
    try:
        system_prompt, prompt_version = load_prompt(cfg, PROMPT_SLUG)
    except FileNotFoundError:
        system_prompt, prompt_version = _LEGACY_SYSTEM_PROMPT, "inline-fallback"

    # --- Perplexity research on competitive position ---
    research_prompt = (
        f"Analyze the competitive moat of {company_name} ({ticker}). "
        f"What are the strongest competitive advantages? "
        f"Who are the closest competitors and how much market share do they have? "
        f"Has the moat strengthened or weakened in the past 3 years? "
        f"For tech/AI companies specifically: is the business becoming more or less "
        f"defensible in the AI era? Be specific with evidence."
    )
    research_text, sources, pplx_cost = p_pplx.research(
        cfg,
        keys,
        research_prompt,
        model=cfg.pplx_model_analysis,
        max_tokens=800,
        recency="month",
    )

    # --- Build Claude prompt ---
    user_prompt = f"""# 审视目标
公司：{company_name} ({ticker})
行业：{sector} / {industry}
科技股模式：{"是" if tech_mode else "否"}

# 业务描述
{biz_summary[:1500]}

# Perplexity 同行 / 竞争格局研究
{research_text}

# Stage 1 财务摘要
{json.dumps(stage1_raw.get('multiples', {}), ensure_ascii=False, indent=2)}

根据以上信息，按系统提示词的格式输出 JSON。"""

    claude_output, claude_cost = p_claude.analyze(
        cfg,
        keys,
        system_prompt,
        user_prompt,
        max_tokens=3000,
    )

    # Parse + validate via pydantic guardrails
    from engine.guardrails import validate_moat

    parsed, parse_errors = validate_moat(claude_output)
    if parse_errors:
        parsed["parse_errors"] = parse_errors
    if not parsed.get("summary_cn"):
        parsed["summary_cn"] = claude_output[:500]

    # Build metrics from parsed result
    metrics = []
    findings = []

    total_score = parsed.get("total_score")
    if total_score is not None:
        metrics.append(
            make_metric(
                "护城河总分",
                total_score,
                "≥ 60 (Munger 标准)",
                total_score >= 60,
                unit="/100",
            )
        )

    bm_score = parsed.get("business_model_score")
    if bm_score is not None:
        metrics.append(
            make_metric(
                "好商业模式 11 条",
                f"{bm_score}/11",
                "≥ 7",
                bm_score >= 7,
            )
        )

    munger_verdict = parsed.get("munger_verdict", "")
    if munger_verdict:
        findings.append(f"**Munger 判断**: {munger_verdict}")

    if parsed.get("strongest_moats"):
        findings.append(f"**最强护城河**: {', '.join(parsed['strongest_moats'])}")
    if parsed.get("strongest_evidence"):
        findings.append(f"**证据**: {parsed['strongest_evidence']}")
    if parsed.get("weakest_link"):
        findings.append(f"**最弱环节**: {parsed['weakest_link']}")
    if parsed.get("tech_moat_trend"):
        findings.append(
            f"**AI 时代趋势**: {parsed['tech_moat_trend']} — {parsed.get('tech_moat_evidence', '')}"
        )
    if parsed.get("lollapalooza"):
        findings.append("🎊 **Lollapalooza 效应**: 多个优势叠加，指数级竞争优势")
    if parsed.get("summary_cn"):
        findings.append(f"\n{parsed['summary_cn']}")

    # --- v0.6 enrichments (findings-only, verdict unaffected) ---
    enrichment_raw = {}
    mda = sec_mda_excerpt(cfg, keys, ticker)
    if mda:
        findings.append("")
        findings.append(mda)
    sentiment_line, sentiment_raw = marketaux_sentiment_summary(cfg, keys, ticker, days=90)
    if sentiment_line:
        findings.append(sentiment_line)
    if sentiment_raw:
        enrichment_raw["marketaux"] = sentiment_raw
    fda_line, fda_raw = fda_pipeline_summary(cfg, keys, company_name, sector)
    if fda_line:
        findings.append(fda_line)
    if fda_raw:
        enrichment_raw["fda_pipeline"] = fda_raw

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "claude_output_raw": claude_output,
            "claude_parsed": parsed,
            "perplexity_research": research_text,
            "perplexity_sources": sources[:10],
            "cost_usd": claude_cost + pplx_cost,
            "prompt_slug": PROMPT_SLUG,
            "prompt_version": prompt_version,
            **({"enrichments": enrichment_raw} if enrichment_raw else {}),
        },
        elapsed_seconds=time.time() - t0,
    )
