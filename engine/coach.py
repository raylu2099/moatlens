"""
Coach commentary generator — turns a raw StageResult into a warm Chinese
paragraph that weaves in a master's quote.

Two modes:
- `haiku` (default): call Claude Haiku with a tight prompt (~$0.005/call)
- `rule`:            use a deterministic template (zero cost, less warmth)

Mode picked via env var MOATLENS_COACH (haiku | rule). If Haiku fails at
runtime, we transparently fall back to the rule template so the stream
never breaks.
"""
from __future__ import annotations

import os

from engine.models import StageResult
from engine.providers import claude as p_claude
from engine.wisdom import Quote
from shared.config import ApiKeys, Config


SYSTEM_PROMPT_COACH = """你是一位价值投资教练，正陪用户在 Moatlens 工具里完成一只股票的 8-stage 审视。

你的任务：根据刚完成的 stage 结果，写一段 150-250 字的中文评论，温暖但直接。必须：

1. 用两三句话**用人话**解释这个 stage 发现了什么（避免术语堆砌）
2. **自然地**把用户提供的大师语录嵌入到评论中 —— 用 blockquote 格式 `>`
3. 解释**为什么这句话此刻适用于这支具体的公司** —— 不能是通用感想
4. 最后一行用一个**具体的 Munger-style 反问**结尾，促使用户思考

**硬规则**：
- 禁止编造大师语录 —— 只用提供的那条
- 禁止给 BUY/SELL 建议
- 禁止超过 250 字
- 中文口语，避免翻译腔
- 不要重复 stage 名称开头；不要"总结"或"综上"
"""


def _rule_template(stage: StageResult, quote: Quote | None, user_context: str = "") -> str:
    """Deterministic fallback when Haiku unavailable or disabled."""
    verdict_cn = {
        "PASS": "通过",
        "FAIL": "不通过",
        "BORDERLINE": "临界",
        "SKIP": "跳过",
    }.get(stage.verdict.value, stage.verdict.value)

    parts = [
        f"**Stage {stage.stage_id} 「{stage.stage_name}」** → {verdict_cn}。",
    ]
    if stage.metrics:
        passed = sum(1 for m in stage.metrics if m.pass_ is True)
        total = sum(1 for m in stage.metrics if m.pass_ is not None)
        if total:
            parts.append(f"指标通过率 {passed}/{total}。")

    if quote and quote.text_cn:
        parts.append("")
        parts.append(f"> {quote.text_cn}")
        if quote.author and quote.source:
            parts.append(f"> — {quote.author}，{quote.source}")
        elif quote.author:
            parts.append(f"> — {quote.author}")
        parts.append("")

    # Munger-style prompting question
    parts.append("**问自己：** 如果这个判断是错的，最可能错在哪个假设上？")
    return "\n".join(parts)


def commentary(
    cfg: Config, keys: ApiKeys,
    stage: StageResult, quote: Quote | None,
    user_context: str = "",
    mode: str | None = None,
) -> str:
    """Return a Chinese commentary string weaving the quote into the stage result."""
    mode = (mode or os.environ.get("MOATLENS_COACH") or "haiku").lower()

    # Always have a safety net via the rule template.
    if mode == "rule" or not keys.anthropic or not quote:
        return _rule_template(stage, quote, user_context)

    # Build Haiku prompt
    metrics_lines = []
    for m in stage.metrics[:6]:
        val = f"{m.value}{m.unit}" if m.value is not None else "—"
        pass_str = "✓" if m.pass_ is True else ("✗" if m.pass_ is False else "·")
        metrics_lines.append(f"- {m.name}: {val}（阈值 {m.threshold}） {pass_str}")

    user_prompt = f"""刚完成的 Stage 信息：

Stage {stage.stage_id}：{stage.stage_name}
判定：{stage.verdict.value}

关键指标：
{chr(10).join(metrics_lines) if metrics_lines else "(无定量指标)"}

前文发现（可选摘录）：
{chr(10).join(stage.findings[:3]) if stage.findings else "(无)"}

{"用户初始论点：" + user_context if user_context else ""}

**必须嵌入的大师语录（不要改动、不要意译）：**
作者：{quote.author}
中文：{quote.text_cn}
英文：{quote.text_en}
出处：{quote.source}

按系统提示的格式输出中文评论，150-250 字。"""

    text, _cost = p_claude.analyze(
        cfg, keys, SYSTEM_PROMPT_COACH, user_prompt,
        model="claude-haiku-4-5", max_tokens=600,
    )

    # If Haiku returned an error stub, degrade gracefully
    if text.startswith("[Claude error") or text.startswith("[ANTHROPIC_API_KEY"):
        return _rule_template(stage, quote, user_context)

    return text.strip()
