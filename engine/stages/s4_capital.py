"""
Stage 4: Management Quality & Capital Allocation.

Philosophy: Once you know the business is great (Stage 3), ask if management
is capable of compounding it. Buffett values management 3 ways:
1. Are they honest? (shareholder letter candor)
2. Do they pass the $1 test? (market cap growth / retained earnings > 1)
3. Capital allocation discipline (buyback at low PE, not high)

Rules:
- Buffett $1 test: ΔMarket Cap / Σ Retained Earnings ≥ 1
- Share count trend: declining (good) or growing (dilutive)
- Buyback timing: bought at low PE (smart) vs high (dumb)
- Insider trades: net buying is bullish

LLM component: analyze recent shareholder letter for tone and candor.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from engine.models import StageResult, Verdict
from engine.providers import claude as p_claude
from engine.providers import financial_datasets as fd
from engine.providers import perplexity as p_pplx
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 4
STAGE_NAME = "管理层 & 资本配置"


def _buffett_dollar_test(income_periods: list[dict], current_market_cap: float) -> dict:
    """Compute Buffett's $1 test over available history."""
    if not income_periods or not current_market_cap:
        return {}

    total_ni = sum(p.get("net_income") or 0 for p in income_periods)
    dividends = sum(abs(p.get("dividends_per_common_share") or 0) * (p.get("weighted_average_shares_diluted") or 0) for p in income_periods)
    retained = total_ni - dividends

    # Rough proxy: current market cap minus market cap N years ago
    # (We don't have historical mcap — use retained earnings test as proxy)
    # For proper test, would need mcap history; approximate with current only
    if retained > 0:
        ratio = current_market_cap / retained  # rough — interpretation: "每留存 1 美元创造 X 美元市值"
        return {
            "cumulative_retained_earnings": retained,
            "current_market_cap": current_market_cap,
            "ratio_proxy": ratio,
            "interpretation": (
                f"累计留存 ${retained/1e9:.1f}B 对应当前市值 ${current_market_cap/1e9:.1f}B。"
                f"这是粗略代理（无历史市值），完整 $1 test 应对比 N 年前市值。"
            ),
        }
    return {"retained": retained, "note": "retained earnings negative or zero"}


SYSTEM_PROMPT = """你是一位分析上市公司管理层与资本配置能力的资深分析师。
应用 Warren Buffett 的评估框架，特别看重：
1. 管理层诚信（股东信坦诚度、是否承认错误、是否解释经营细节）
2. 资本分配记录（回购时机 = 低 PE 还是高 PE、并购整合能力、股息政策）
3. 是否把股东当合伙人（而非职业经理人的短期业绩取向）

根据提供的信息，严格按以下 JSON 格式输出：

```json
{
  "integrity_score": 0-20,
  "capital_allocation_score": 0-20,
  "shareholder_orientation_score": 0-20,
  "integrity_evidence": "具体例子",
  "capital_evidence": "具体例子",
  "red_flags": ["..."],
  "buffett_verdict_cn": "值得信任 | 谨慎观察 | 警惕 | 回避",
  "summary_cn": "200 字以内总结"
}
```
"""


def run(
    cfg: Config, keys: ApiKeys, ticker: str,
    stage1_raw: dict,
) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=10)
        insider = fd.fetch_insider_trades(cfg, keys, ticker, limit=20)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    multiples = yfp.fetch_multiples(ticker)
    company = yfp.fetch_company_info(ticker)
    company_name = company.get("long_name", ticker)

    metrics = []
    findings = []

    # --- Share count trend (dilutive or accretive) ---
    if len(income.periods) >= 5:
        recent_shares = income.periods[0].get("weighted_average_shares_diluted") or 0
        old_shares = income.periods[4].get("weighted_average_shares_diluted") or 0
        if old_shares > 0:
            share_change_pct = (recent_shares - old_shares) / old_shares * 100
            pass_share = share_change_pct <= 0  # ideally decreasing
            metrics.append(make_metric(
                "股份变化 (5Y)", round(share_change_pct, 1),
                "≤ 0% (应减少)", pass_share, unit="%",
                note="回购 = 负值更好；稀释 = 正值差",
            ))

    # --- Buffett $1 test ---
    buffett = _buffett_dollar_test(income.periods, multiples.market_cap or 0)
    if buffett.get("ratio_proxy"):
        r = buffett["ratio_proxy"]
        metrics.append(make_metric(
            "Buffett $1 Test (proxy)", round(r, 2),
            "> 1.0", r > 1.0, unit="x",
            note=buffett.get("interpretation", ""),
        ))

    # --- Insider trading signal ---
    net_shares = 0.0
    buy_count = 0
    sell_count = 0
    for t in insider:
        shares = t.get("transaction_shares") or 0
        ttype = (t.get("transaction_type") or "").lower()
        if "purchase" in ttype or "open market buy" in ttype:
            net_shares += shares
            buy_count += 1
        elif "sale" in ttype or "sell" in ttype or "disposition" in ttype:
            net_shares -= shares
            sell_count += 1
    if insider:
        metrics.append(make_metric(
            "内部人交易 (近 20 笔)",
            f"{buy_count}买/{sell_count}卖",
            "净买入 > 净卖出",
            net_shares > 0,
            note=f"净 {net_shares:+,.0f} 股",
        ))

    # --- Perplexity research on recent shareholder letter + management commentary ---
    research_prompt = (
        f"Summarize key points from {company_name}'s most recent CEO shareholder "
        f"letter or annual report introductory letter. What does the CEO say about: "
        f"(1) mistakes made, (2) capital allocation priorities, (3) the company's "
        f"long-term strategy? Be specific with quotes. Also note any controversies "
        f"around executive compensation or related-party transactions from the "
        f"past 12 months."
    )
    research_text, sources, pplx_cost = p_pplx.research(
        cfg, keys, research_prompt,
        model=cfg.pplx_model_analysis, max_tokens=800, recency="year",
    )

    # --- Claude analyze ---
    user_prompt = f"""# 分析对象
{company_name} ({ticker})

# 定量信号
- 股份变化 5Y: {[m for m in metrics if '股份变化' in m.name][0].value if any('股份变化' in m.name for m in metrics) else 'n/a'}%
- Buffett $1 test proxy: {[m for m in metrics if '$1 Test' in m.name][0].value if any('$1 Test' in m.name for m in metrics) else 'n/a'}x
- 近期内部人: 买{buy_count} 卖{sell_count}, 净 {net_shares:+,.0f} 股

# Perplexity 研究：股东信与管理层记录
{research_text}

请严格按系统提示词的 JSON 格式输出。"""

    claude_output, claude_cost = p_claude.analyze(
        cfg, keys, SYSTEM_PROMPT, user_prompt, max_tokens=2000,
    )

    parsed = {}
    try:
        text = claude_output.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        parsed = json.loads(text.strip())
    except Exception:
        parsed = {"summary_cn": claude_output[:500]}

    # Metrics from Claude
    integ = parsed.get("integrity_score")
    if integ is not None:
        metrics.append(make_metric(
            "诚信度 (Claude)", integ, "≥ 14", integ >= 14, unit="/20",
        ))
    cap = parsed.get("capital_allocation_score")
    if cap is not None:
        metrics.append(make_metric(
            "资本分配能力 (Claude)", cap, "≥ 14", cap >= 14, unit="/20",
        ))

    if parsed.get("buffett_verdict_cn"):
        findings.append(f"**Buffett 判断**: {parsed['buffett_verdict_cn']}")
    if parsed.get("red_flags"):
        findings.append("**红旗**: " + "; ".join(parsed["red_flags"]))
    if parsed.get("summary_cn"):
        findings.append(f"\n{parsed['summary_cn']}")

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "buffett_test": buffett,
            "insider_net_shares": net_shares,
            "claude_parsed": parsed,
            "perplexity_research": research_text,
            "cost_usd": claude_cost + pplx_cost,
        },
        elapsed_seconds=time.time() - t0,
    )
