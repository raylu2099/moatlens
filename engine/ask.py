"""
/ask mode — Perplexity-style Q&A on a ticker.

Takes natural-language input, uses Haiku to route intent → set of relevant
stages, runs only those, produces a structured answer with master-quote
citations.

Never runs stages 3/4/8 unless explicitly needed — /ask is meant to be
cheap and fast. Deep audits should go through /chat.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator

from engine.models import StageResult, Verdict
from engine.providers import claude as p_claude
from shared.config import ApiKeys, Config


# -----------------------------------------------------------------------
# Intent routing
# -----------------------------------------------------------------------

INTENT_KEYWORDS = {
    # keyword → relevant stage ids
    "值得买": [1, 6, 7],
    "该买": [1, 6, 7],
    "买入": [1, 6, 7],
    "好公司": [1, 3],
    "护城河": [3],
    "moat": [3],
    "管理层": [4],
    "管理": [4],
    "CEO": [4],
    "利润质量": [2, 5],
    "会计": [2, 5],
    "估值": [6, 7],
    "贵不贵": [6, 7],
    "便宜": [6, 7],
    "合理价": [6, 7],
    "安全边际": [7],
    "减仓": [7],
    "卖出": [7],
    "风险": [8, 7],
    "失败": [8],
    "泡沫": [7, 8],
}

STAGE_NAMES_CN = {
    1: "能力圈 & 垃圾桶测试",
    2: "诚实度测谎",
    3: "护城河深度验证",
    4: "管理层 & 资本配置",
    5: "所有者盈利 & 财务质量",
    6: "估值 (DCF)",
    7: "安全边际 & 非对称性",
    8: "反方论点 & Variant View",
}


@dataclass
class AskIntent:
    query: str
    ticker: str
    stages: list[int]
    rationale: str      # human-readable Chinese explanation of why these stages


def keyword_route(query: str) -> tuple[list[int], str] | None:
    """Fast keyword-based intent routing. Returns (stages, rationale) or None."""
    q = query.lower()
    matched: set[int] = set()
    hits: list[str] = []
    for kw, stages in INTENT_KEYWORDS.items():
        if kw.lower() in q:
            matched.update(stages)
            hits.append(kw)
    if matched:
        stages_sorted = sorted(matched)
        names = [STAGE_NAMES_CN[s] for s in stages_sorted]
        rationale = f"匹配关键词 {hits} → 跑 Stage {stages_sorted} ({names[0]}等)"
        return stages_sorted, rationale
    return None


def haiku_route(cfg: Config, keys: ApiKeys, query: str) -> tuple[list[int], str]:
    """
    Claude Haiku intent routing. Falls back to "run all 8" if Haiku unavailable.
    Cost ~$0.005/call.
    """
    if not keys.anthropic:
        return list(range(1, 9)), "（未配置 Claude key，默认跑全部 8 stage）"

    system = """你是 Moatlens 的意图路由器。用户问了一个关于股票的问题，你需要判断哪些 stage 要跑。

8 个 stage:
1. 能力圈 & 垃圾桶 (ROIC/毛利/利息覆盖/Z-score)
2. 诚实度测谎 (利润质量, 会计红旗)
3. 护城河 (需要 Claude + Perplexity, $0.25)
4. 管理层 (需要 Claude + Perplexity, $0.25)
5. 所有者盈利 (SBC调整/DuPont)
6. 估值 (DCF/反向DCF/MC)
7. 安全边际 & 非对称性 (需要 stage 6 做完)
8. 反方论点 (需要 Claude, 基于前面 stage, $0.25)

规则：
- 问"值得买吗" → 通常 1, 5, 6, 7
- 问"护城河" → 只需 1, 3
- 问"管理层" → 只需 1, 4
- 问"估值贵不贵" → 只需 1, 6, 7
- 问"风险/失败" → 需要 3, 6, 7, 8
- 泛泛"审视"或"看看" → 全 8 个
- 如果不确定 → 保守地只选最相关的 2-3 个

输出严格 JSON：
{"stages": [1, 6, 7], "rationale": "用户问估值相关，无需跑护城河/管理层深度分析"}
"""
    text, _cost = p_claude.analyze(
        cfg, keys, system, f"用户问题：{query}",
        model="claude-haiku-4-5", max_tokens=300,
    )
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("no json")
        data = json.loads(m.group(0))
        stages = sorted(set(int(s) for s in data.get("stages", []) if 1 <= int(s) <= 8))
        rationale = str(data.get("rationale", ""))[:200]
        if not stages:
            return [1, 6, 7], "（Haiku 未指定 stage，默认 1/6/7）"
        return stages, rationale
    except Exception:
        return [1, 6, 7], "（Haiku 解析失败，默认 1/6/7）"


def route_intent(cfg: Config, keys: ApiKeys, query: str, ticker: str) -> AskIntent:
    """Route user query to stage subset. Tries keyword first (free), then Haiku."""
    kw = keyword_route(query)
    if kw is not None:
        stages, rationale = kw
    else:
        stages, rationale = haiku_route(cfg, keys, query)
    return AskIntent(query=query, ticker=ticker, stages=stages, rationale=rationale)


# -----------------------------------------------------------------------
# Answer synthesis
# -----------------------------------------------------------------------

@dataclass
class AnswerBlock:
    """One section of the structured answer."""
    heading: str           # e.g. "质量", "估值", "安全边际"
    verdict: str           # "✅" / "🟡" / "❌"
    prose: str             # 2-3 sentences with [n] citation markers
    metrics: list[dict]    # rendered metric dicts
    citation_ids: list[str]  # references to wisdom.yaml entries


def _stage_to_block(stage: StageResult) -> AnswerBlock:
    """Turn a raw StageResult into a display block."""
    verdict_mark = {
        Verdict.PASS: "✅",
        Verdict.BORDERLINE: "🟡",
        Verdict.FAIL: "❌",
        Verdict.SKIP: "⊘",
    }.get(stage.verdict, "")

    heading_map = {
        1: "质量", 2: "诚实度", 3: "护城河", 4: "管理层",
        5: "所有者盈利", 6: "估值", 7: "安全边际", 8: "反方论点",
    }
    heading = heading_map.get(stage.stage_id, stage.stage_name)

    # Build prose from findings (truncated)
    prose_parts = []
    for f in stage.findings[:2]:
        # Strip common markdown markers for clean prose
        clean = re.sub(r"^\*+|\*+$", "", f).strip()
        if clean and not clean.startswith("⚠️ 能力圈自检"):
            prose_parts.append(clean)
    prose = " ".join(prose_parts)[:300]

    metrics = []
    for m in stage.metrics[:5]:
        val = m.value
        if val is None:
            val = "—"
        metrics.append({
            "name": m.name, "value": val, "unit": m.unit,
            "threshold": m.threshold, "pass": m.pass_, "note": m.note,
        })

    return AnswerBlock(
        heading=heading, verdict=verdict_mark,
        prose=prose, metrics=metrics, citation_ids=[],
    )


# -----------------------------------------------------------------------
# Event stream for SSE
# -----------------------------------------------------------------------

Event = tuple[str, dict]


def stream_ask(cfg, keys, ask_session) -> Iterator[Event]:
    """
    Stream an /ask audit: route intent → run selected stages → stream blocks
    with wisdom citations → final summary with continue-suggestions.
    """
    from engine import wisdom as wisdom_mod
    from engine.orchestrator import _run_stage_safe, STAGES
    from engine.models import AuditReport
    from datetime import datetime
    from engine.providers import yfinance_provider as yfp
    from shared.ask import save_ask_session

    ask_session.status = "routing"
    save_ask_session(cfg, ask_session)

    yield "thinking", {"text": "正在解析你的问题..."}

    intent = route_intent(cfg, keys, ask_session.query, ask_session.ticker)
    ask_session.selected_stages = intent.stages
    ask_session.intent_rationale = intent.rationale
    ask_session.status = "running"
    save_ask_session(cfg, ask_session)

    yield "intent", {
        "stages": intent.stages,
        "stage_names": [STAGE_NAMES_CN.get(s, f"Stage {s}") for s in intent.stages],
        "rationale": intent.rationale,
    }

    company = yfp.fetch_company_info(ask_session.ticker)
    report = AuditReport(
        ticker=ask_session.ticker,
        company_name=company.get("long_name", ask_session.ticker),
        audit_date=datetime.now().strftime("%Y-%m-%d"),
        generated_at=datetime.now(),
        anchor_thesis=ask_session.query,
    )
    stage_fns = {sid: fn for sid, fn in STAGES}
    prior: dict[int, dict] = {}

    # Always include dependency stages (e.g. stage 7 needs stage 6 raw)
    effective = set(intent.stages)
    if 7 in effective:
        effective.add(6)
    if 8 in effective:
        effective |= {3, 4, 6, 7}
    # Run in canonical order
    to_run = sorted(effective)

    used_quote_ids: set[str] = set()
    blocks: list[AnswerBlock] = []

    for sid in to_run:
        yield "stage_start", {"stage_id": sid, "stage_name": STAGE_NAMES_CN.get(sid, f"Stage {sid}")}
        result = _run_stage_safe(
            sid, stage_fns[sid], cfg, keys, ask_session.ticker,
            tech_mode=False, prior=prior, anchor_thesis=ask_session.query,
            my_variant_view="",
        )
        report.stages.append(result)
        prior[sid] = result.raw_data

        # Only emit blocks for stages the user asked about (not dependencies)
        if sid in intent.stages:
            block = _stage_to_block(result)
            # Attach a matching wisdom quote
            q = wisdom_mod.pick_for_stage(
                cfg, sid, ask_session.session_id, exclude_ids=used_quote_ids,
            )
            if q:
                used_quote_ids.add(q.id)
                block.citation_ids = [q.id]
                yield "quote", {
                    "stage_id": sid,
                    "quote": {
                        "id": q.id, "author": q.author,
                        "text_cn": q.text_cn, "text_en": q.text_en,
                        "source": q.source,
                    },
                }
            blocks.append(block)
            yield "answer_block", {
                "stage_id": sid,
                "heading": block.heading, "verdict": block.verdict,
                "prose": block.prose, "metrics": block.metrics,
                "citation_ids": block.citation_ids,
            }
        else:
            # Dependency only — tell client we ran it silently
            yield "dep_stage", {"stage_id": sid, "verdict": result.verdict.value}

    # Final synthesis
    short_answer = _synthesize_short_answer(blocks)
    ask_session.status = "complete"
    save_ask_session(cfg, ask_session)

    yield "final", {
        "short_answer": short_answer,
        "blocks_count": len(blocks),
        "citations_count": len(used_quote_ids),
        "continue_suggestions": _continue_suggestions(intent, blocks),
    }


def _synthesize_short_answer(blocks: list[AnswerBlock]) -> str:
    """1-2 sentence summary from block verdicts."""
    pass_ct = sum(1 for b in blocks if b.verdict == "✅")
    fail_ct = sum(1 for b in blocks if b.verdict == "❌")
    borderline_ct = sum(1 for b in blocks if b.verdict == "🟡")

    if fail_ct == 0 and pass_ct > 0 and borderline_ct == 0:
        return "全部通过你关心的检查项 —— 但这不等于『该买』，还要看估值和你的 variant view。"
    if fail_ct >= 2:
        return "多项关键检查不通过。 **先不要急**。"
    if borderline_ct > pass_ct:
        return "临界信号较多 —— 这支需要更深入的观察，而非立即决策。"
    return f"{pass_ct} 项通过 / {borderline_ct} 项临界 / {fail_ct} 项失败。查看下方细节再下判断。"


def _continue_suggestions(intent: AskIntent, blocks: list[AnswerBlock]) -> list[str]:
    """Follow-up question suggestions."""
    suggestions = []
    ran_stages = set(intent.stages)
    if 3 not in ran_stages:
        suggestions.append(f"{intent.ticker} 的护城河怎么样？")
    if 4 not in ran_stages:
        suggestions.append(f"{intent.ticker} 的管理层值得信任吗？")
    if 8 not in ran_stages:
        suggestions.append(f"{intent.ticker} 最可能怎么失败？")
    if 7 in ran_stages:
        suggestions.append(f"什么价位 {intent.ticker} 才值得加仓？")
    return suggestions[:4]
