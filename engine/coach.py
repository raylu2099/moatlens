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


# Stage-specific Munger-style reflection prompts.
# Keyed by (stage_id, verdict). Fallback to generic prompt if no match.
#
# Designed to avoid the "again with the same question" fatigue that affects
# the generic template. Each prompt is concrete to the stage's failure mode
# or the specific next question a careful investor would ask.
_STAGE_PROMPTS: dict[tuple[int, str], str] = {
    # Stage 1 — Competence & hygiene
    (1, "PASS"): "你说得出这家公司 10 年前是什么样子吗？说不出来，'能力圈内' 就只是口头禅。",
    (1, "FAIL"): "你是真的**不懂**这行，还是只是**不敢**买？如果是后者，补课；如果是前者，别自欺。",
    (1, "BORDERLINE"): "边界模糊时，Buffett 的话是 '等到下一个'。真的没有更清楚的机会了吗？",
    # Stage 2 — Financial integrity (earnings quality, altman Z, liquidity)
    (
        2,
        "PASS",
    ): "报表干净不等于生意好。干净只是 0 分线。真正的问题：下一个 stage 会证明它配不配被审视下去。",
    (2, "FAIL"): "财务美化通常是管理层恐惧的信号。**怕什么**？是经营失速，还是偿债？",
    (
        2,
        "BORDERLINE",
    ): "灰色地带的数字背后往往是行业结构性变化，不是一次性瑕疵。这家公司的行业还在向上吗？",
    # Stage 3 — Moat
    (
        3,
        "PASS",
    ): "护城河存在只是必要条件。它是在**变深**还是在**变浅**？AI / 新进入者 / 监管，谁在挖地基？",
    (3, "FAIL"): "没有护城河 = 回归平均利润率 = DCF 假设被腰斩。你是在为增长付钱，不是为品质付钱。",
    (3, "BORDERLINE"): "护城河 + 高估值 = 等待；护城河 + 低估值 = 无脑买。你现在在哪个象限？",
    # Stage 4 — Management & capital allocation
    (4, "PASS"): "信任管理层的极限：别被坦诚的股东信骗了。他们**行动**和**文字**一致吗？",
    (4, "FAIL"): "管理层不可信，再好的生意也会被糟蹋。是换人的时间，还是走人的时间？",
    (4, "BORDERLINE"): "回购时机 + 并购记录 = 管理层真实能力。他们在高位回购过吗？",
    # Stage 5 — Owner Earnings / true FCF
    (
        5,
        "PASS",
    ): "Owner Earnings 好 ≠ 能延续。维护 Capex 低是因为**资产轻**，还是因为**在透支未来**？",
    (5, "FAIL"): "利润是观点，现金流是事实。事实不给你现金，再多调整项也只是话术。",
    (
        5,
        "BORDERLINE",
    ): "SBC 扣除后 Owner Earnings 还站得住吗？尤其是科技股，这是最容易被粉饰的一环。",
    # Stage 6 — Valuation (DCF)
    (6, "PASS"): "模型算出来的 IV 只是**一张纸**。你真敢在这个价格附近**加仓到核心仓位**吗？",
    (
        6,
        "FAIL",
    ): "价格 > 你的 IV 只意味着两件事之一：市场看到你没看到的，或者市场错了。哪个你更敢赌？",
    (6, "BORDERLINE"): "DCF 三场景的假设，换哪一个会翻转判断？这就是你的单一论点风险点。",
    # Stage 7 — Safety margin / asymmetry / Kelly
    (
        7,
        "PASS",
    ): "MOS 充足只解决了'何时买'，没解决'买多少'。Kelly 告诉你上限，但你的能力圈深度才是真实上限。",
    (
        7,
        "FAIL",
    ): "溢价买入 = 在为其他买家的乐观付钱。**你**的非共识观点是什么？说不出来就不该出手。",
    (
        7,
        "BORDERLINE",
    ): "安全边际不够、非对称也不够 —— Howard Marks 会说这不是机会，是诱惑。再等一等。",
    # Stage 8 — Inversion & Variant View
    (
        8,
        "PASS",
    ): "你列出了 3 种失败路径。问自己：**有没有第 4 种你不敢列出来的**？那条往往才是真的。",
    (8, "FAIL"): "Inversion 失败意味着你还没真正想过'怎么会错'。Munger 不会按 BUY 直到这一关过。",
    (8, "BORDERLINE"): "Variant View 和共识差别太小 = 没有 alpha。你的判断是不是其实就是共识包装？",
}

_GENERIC_PROMPT = "如果这个判断是错的，最可能错在哪个假设上？"


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

    # Stage-aware Munger prompt (falls back to generic if no match)
    prompt = _STAGE_PROMPTS.get((stage.stage_id, stage.verdict.value), _GENERIC_PROMPT)
    parts.append(f"**问自己：** {prompt}")
    return "\n".join(parts)


def commentary(
    cfg: Config,
    keys: ApiKeys,
    stage: StageResult,
    quote: Quote | None,
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
        cfg,
        keys,
        SYSTEM_PROMPT_COACH,
        user_prompt,
        model="claude-haiku-4-5",
        max_tokens=600,
    )

    # If Haiku returned an error stub, degrade gracefully
    if text.startswith("[Claude error") or text.startswith("[ANTHROPIC_API_KEY"):
        return _rule_template(stage, quote, user_context)

    return text.strip()
