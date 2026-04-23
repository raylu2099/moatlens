# ADR 009 — 期权（LEAPS）在审视范围之外

**Status:** Accepted
**Date:** 2026-04-22
**Related to:** project-level `CLAUDE.md` hard constraints section

## Context

Ray 的真实持仓结构（2026-04 现状）：
- NVO 40%、META 40%
- 剩余 20% 是 **NVDA 2028 年到期的 LEAPS 期权**（美式看多/看空不在此决策范围）

v0.5 完成后的 subagent 产品审视（2026-04-22）明确指出：

> 工具评估的是"好公司"，Ray 持有的可能是"期权衍生品"。硬约束"不提供期权策略建议"很诚实，但以至于 Ray 全然无法从 Moatlens 看到期权到期时间压力、IV crush、theta 衰减。每次 NVDA 审视后 Ray 仍需要另一个系统看期权风险。

这是工具 vs Ray 真实持仓的最大不对齐。产品审视官打分 **2/5**（三个持仓里最低）。

## Decision

**不加**期权功能。明确这是设计边界而非遗漏。具体：

1. **保留**硬约束："Do not propose or add … short-selling mechanics, options strategies"
   （见项目级 `CLAUDE.md`）
2. **保留**：Moatlens 只评估 underlying（底层股票），不评估 derivative
3. **明确**：LEAPS、covered call、protective put、cash-secured put 等任何期权合约
   风险参数（theta、vega、gamma、IV 百分位、moneyness、DTE 衰减）**不在本工具范围**
4. **不做**：不加"期权风险体检"卡片、不加"持有 LEAPS 时的警告"、不给
   "几号该 roll over" 类建议

## Why not expand

1. **违反 Buffett/Munger 哲学核心**。Buffett 说过："我们不做期权，因为投机和投资
   之间的界线非常清楚。我们站在投资那一侧。" 如果工具给期权建议，工具就不再是
   "价值投资审视工具"。
2. **信号与噪音的比例会劣化**。期权价格短期波动远超 underlying，加入期权
   指标会**诱导**用户看更多短期信号，违反 Munger "activity is the enemy"。
3. **用户负担显性化**。Ray 知道 LEAPS 风险管理不在 Moatlens 里 —— 这是
   **已知的已知**。把它文档化（本 ADR）比默认沉默更诚实。

## Consequences

### Ray 的工作方式（显式）

- 审视 NVDA（底层）→ Moatlens 给"公司是否值得长期持有"的判断
- 管理 NVDA LEAPS（衍生品）→ Ray 自己在其他工具里做（券商 Greeks、optionsprofitcalculator、IVRank 工具等）
- 两者**不交叉污染**：Moatlens 审视说 NVDA "公司端仍强"，不等于 LEAPS 合约
  本身赚钱；相反 IV crush 使 LEAPS 亏钱也不意味 Moatlens 审视错了

### 对未来 Claude Code 会话的明确指引

- **不要**重复建议"加期权体检"。如审视报告提到，确认这是已决策边界
- **不要**修改硬约束第 7 条（options strategies 禁项）
- 若 Ray 主动要求期权功能，把他引导到**另外**一个项目（新建 repo），不要污染 Moatlens

### 三个月自评（2026-07-18）可能出现的信号

如果到期时 Ray 发现：
- ✅ LEAPS 风险用其他工具管理得当，Moatlens 审视 NVDA 仍有价值 → 保持此 ADR
- ❌ Moatlens 审视 NVDA 时缺失期权视角导致决策不完整 → 不是加期权，
  而是考虑"在 /portfolio 标记 LEAPS 持仓时提示 '本工具不处理期权风险'"
  的一句话提醒

## Alternatives considered

1. **加轻量"期权风险快照"卡片**（theta/IV/DTE 只读展示）—— 拒绝，理由见
   "Why not expand" 第 2 点。
2. **在硬约束里再加一条 'also no covered call docs'** —— 多余，现有"options
   strategies"一条已覆盖。
3. **建议 Ray 卖掉 LEAPS 换 NVDA 股票** —— 这是 investment advice，超出工具角色。

## References

- 2026-04-22 subagent 审视报告 (Agent 3: Product & Value-Investing Strategy)
- 项目级 `CLAUDE.md` → "Product philosophy (hard constraints)"
- `/var/services/homes/hellolufeng/.claude/projects/-volume1-homes-hellolufeng/memory/project_moatlens.md`
