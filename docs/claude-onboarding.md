# Claude Onboarding Brief — Moatlens

> **为什么存在这份文档**：Ray 在 NAS 和 MacBook 两台机器上都用 Claude Code
> 开发这个项目，但两边 Claude 的 memory（`~/.claude/projects/...`）彼此不
> 共享。Synology Drive 同步源码，所以把"NAS 端那个 Claude 积累的非代码知识"
> 写进项目里，Mac 端 Claude `git pull` 就能拿到同等上下文。
>
> **和 `CLAUDE.md` 的分工**：`CLAUDE.md` 是**规则/指令**（硬约束、架构、workflow）。
> 这份是**画像/历史/启发式**（Ray 的合作风格、已拒绝过的思路、常见诊断直觉）。
>
> **和 ADR 的分工**：ADR 是**架构决定**（为什么选 X 不选 Y）。
> 这份是**会话级经验**（Ray 在过程中说过什么、踩过什么坑）。

---

## 1. 10 秒 TL;DR

- **Moatlens** = Ray 个人用的价值投资审视工具（Buffett / Munger / Marks / Bolton 框架，8 个 stage）。**不是 SaaS**，不是朋友共享，是他自己一个人用的决策陪练
- **单用户**：无 auth，web 绑 `0.0.0.0:48291`（NAS tmux `moatlens-web`）或 `127.0.0.1:48291`（Mac 本地），API keys 从 `.env` 读
- **当前版本**：v0.6（2026-04-23 刚 commit + push），161 tests 全绿，doctor 9/9
- **上一轮做完了什么**：见 `_WORK.md`（如果还在）或 `git log`
- **下一步做什么**：见 `_WORK.md`（如果有且状态=进行中）或问 Ray

---

## 2. 谁是 Ray，怎么和他合作

### 偏好 & 沟通风格
- **中文**，技术术语保留英文（如 ROIC、DCF、MOS、Kelly）
- **直接、不客套**；"报告失败原因"比"做了什么"更有价值
- 喜欢**短句、表格、精确路径**（file:line_number），不喜欢寒暄开头
- 对**确认性问题**敏感 —— "要我现在 commit 吗？"这种询问多了会被打回。完成工作后自然的下一步直接做
- **先做，最后汇报**（autonomous operation）；除非是敏感/不可逆操作（force push、reset --hard、公网暴露、花钱的 API 循环等）

### 已明确表态过的合作规则（按时间排序）
| 时间 | Ray 说法 | 意思 |
|---|---|---|
| 早期 | "你自主工作，最后报告失败" | 不要中途一步一步问 |
| 2026-04-19 | "别只读配置就报告系统行为" | 核实脚本/日志 mtime，用实际状态 |
| 2026-04-20 | "别给我期权/技术指标/情绪指标建议" | 硬约束写进了 `CLAUDE.md` |
| 2026-04-21 | "market-intel / moatlens / market-intel-app 三个项目独立" | 不要跨项目污染会话 |
| 2026-04-23 | "git 操作按最佳实践自主执行" | commit/push/tag 不用问 |

### 已被他否决过、**不要重新建议**的点子
- ❌ 给 Moatlens 加公网 auth / OAuth（单用户 + Tailscale 够用，见 ADR 001）
- ❌ 把 `.env` 搬出 Drive 同步路径（他确认同步到 Mac 是**特性**不是 bug）
- ❌ 加任何期权/theta/IV 卡片（见 ADR 009）
- ❌ 加技术指标 / 止损逻辑 / 情绪指标 / 日推送
- ❌ 加 hooks / subagents / MCP server（NAS 资源有限，见 NAS-level `CLAUDE.md`）
- ❌ 把 market-intel / moatlens / market-intel-app 抽共享库

---

## 3. Ray 是谁（工具适配度视角）

- 在 NAS（DS224+ 在加州）+ Mac（随身）+ iPhone 上操作，通过 Tailscale mesh 互联
- **持仓结构**（不写具体仓位，避免敏感信息泄露到 GitHub）：
  - 重仓医药（GLP-1 相关，Moatlens 支持医药股审视但 pipeline 数据是盲点 → v0.6 补了 FDA 集成）
  - 重仓广告科技 + AI 平台公司
  - 少部分是 **LEAPS 期权**（AI 半导体，2028 到期）—— 这是 Moatlens 硬约束边界外的，见 ADR 009
- 三个月自评截止日：**2026-07-18**。3 个问题（见 `CLAUDE.md` 底部）决定要不要把 Moatlens 当创业产品做
- 另外他还在运营 `market-intel`（每日 5-7 次 Perplexity 搜索 + Telegram 推送）和 `market-intel-app`（另一个独立项目）

---

## 4. 技术架构一页纸

```
User (Ray)
   │
   ├─ CLI (python -m cli audit AAPL)  ← truth source
   │      └─ engine/orchestrator.run_audit_auto/wizard
   │             ├─ engine/stages/s1..s8 (business logic)
   │             ├─ engine/providers/  (9 APIs)
   │             ├─ engine/stages/_enrichments.py  (v0.6, findings-only color)
   │             ├─ engine/guardrails.py  (Claude JSON pydantic contracts)
   │             └─ shared/storage.py  (filesystem, fcntl lock)
   │
   └─ Web (uvicorn 0.0.0.0:48291, FastAPI + Jinja2 + HTMX + Tailwind CDN)
          ├─ /                三卡片首页
          ├─ /ask/*           Perplexity-style Q&A（意图路由 → 部分 stage）
          ├─ /chat/*          教练模式（完整 8 stage + SSE 流式 + 大师语录）
          ├─ /portfolio       持仓看板 + 重审视提醒（v0.6 🔔）
          ├─ /history         audit 历史
          ├─ /audit/<t>/<date>  历史报告
          ├─ /wisdom          45 条大师语录库
          └─ /api/status      healthcheck
```

### 关键文件速查
见 `CLAUDE.md` → "Where things are" 表格，已经很完整。这里补充几条不在表里的：

| 这个问题的答案在哪 | 文件 |
|---|---|
| 为什么 s5 的 `_dupont` 不除以 100 | `engine/stages/s5_owner_earnings.py` 注释 + git blame |
| 为什么 s6 的 bracket 是 `[-20, 100]%` | `engine/stages/s6_valuation.py::_reverse_dcf_implied_growth` |
| 为什么 stage 8 有 gating | `engine/orchestrator.py` 搜 "useful_signals" |
| 45 条语录怎么选到某个 stage | `engine/wisdom.py::pick_for_stage` |
| Coach 的 stage-specific prompts | `engine/coach.py::_STAGE_PROMPTS` (v0.6 加的) |
| 为什么 Mac 和 NAS 的 data/ 不共享 | `MOATLENS_DATA_DIR` env + `feedback_synology_drive_python.md` |

### 9 个 API（来源真实性排序，**不是价值排序**）
```
financial_datasets  → 财报硬数字 (必须)
fred                → 无风险利率 (必须，DCF 用)
perplexity          → 定性研究 (必须，s3/s4 用)
anthropic           → stage 3/4/8 分析 + coach (必须)
yfinance            → 实时价 + 公司信息 (免费)
sec_api_io          → SEC 原文 MD&A/Risk Factors (v0.6 新，可选)
finnhub             → insider + analyst 共识 (v0.6 新，可选)
marketaux           → 新闻情绪 (v0.6 新，可选)
openfda/ClinicalTrials → 医药 pipeline (v0.6 新，免费)
```

---

## 5. 硬约束速查（复制自 CLAUDE.md，简化版）

**永远不要做**：
- 技术指标（RSI / MACD / Bollinger / SMA）
- 情绪指标（VIX / put-call / fear-greed）
- 硬止损逻辑（违反 Buffett "falling price = better deal"）
- 每日推送 / 实时提醒（违反 Munger "activity is the enemy"）
- 期权策略 / 做空机制（见 ADR 009）

**永远保留**：
- 价值投资 8 stage（Buffett / Munger / Marks / Bolton / Graham）
- 基本面指标（ROIC / OE / DCF / moat / 管理层）
- 中文 UI / 英文术语（见 ADR 004）
- 单用户 + filesystem 存储 + `.env` keys（ADR 001 / 002 / 003）
- 一个 logical change 一个 commit；结构性改动前打 tag

---

## 6. Ray 工作方式几条"启发式"

这些是读一百篇 memory 都看不出来、但和他合作多了会摸到的规律：

1. **"核实再报告"** —— 问"现在跑什么"时，不要只看 cron/config，要 `ls` 脚本存在性 + 看日志 mtime。2026-04-19 栽过一次（给 Ray 的推送时间表配置里写的 5 条，实际上从 4/17 就静默失败了）
2. **长流程任务他喜欢 parallel subagents 审视** —— 见 2026-04-22 做的 3-agent 审视（安全/架构/产品三视角），他觉得值
3. **审视过后的 P0/P1/P2 清单**，他常答"P0-X 不做，其他全做" —— 不是懒，是他评估过 trade-off
4. **commit 粒度偏好**：一个 feature release（比如 v0.6）= 一个大 feature commit + 一个独立 doc commit；而不是按文件类型拆 5 个小 commit（pre-commit hook 对跨 commit 依赖不友好）
5. **敏感但不过度敏感** —— 持仓结构 OK 提（抽象层面），具体仓位数字不要写进 git tracked 文件
6. **运维层面爱玩自己搭基础设施** —— Tailscale、tmux、cron、sing-box、Synology Drive 他都自己维护，所以可以放心建议这些
7. **"再多建议也要做"** —— 有一次他说"你有'只说不做'的倾向"，后来我试着低风险的直接 do（比如 cron 清理、backup 扩展），他接受度反而更好

---

## 7. 跨机器（NAS ↔ Mac）工作注意

来自 `feedback_synology_drive_python.md`（memory）的精华：

| 坑 | 对策 |
|---|---|
| `.venv/` 进 Drive 同步 → Mac Python 3.13 和 NAS 3.12 二进制不兼容 | venv 放 `~/.venvs/moatlens`（Mac）或只在 NAS 用 micromamba env `ytdlp` |
| `__pycache__` 双向同步产生 conflict | 两边都 `export PYTHONDONTWRITEBYTECODE=1` |
| `data/audits/AAPL/2026-04-23.json` Mac/NAS 都写 → 互相覆盖 | Mac 端 `export MOATLENS_DATA_DIR=~/.moatlens/data` |
| Mac 启动 uvicorn 用 `0.0.0.0` 暴露 LAN | Mac 端只绑 `127.0.0.1:48291` |
| 两边都有本地 commit → push 冲突 | 干活前 `git pull --rebase`；push 失败就 pull rebase 再 push |
| Mac 端 pip install 了新依赖但没更新 requirements.txt | 装完顺手 `pip freeze` 看看要不要同步 |
| Mac 端没装 `pre-commit install` → 绕过 hook | Mac 一次性做：`pip install pre-commit && pre-commit install` |

### Mac 首次启动 Claude 的推荐起手式
```bash
cd ~/SynologyDrive/moatlens   # 或你的实际路径
git pull --rebase
# 然后启动 Claude Code，第一句话就是：
#   "读 CLAUDE.md + docs/claude-onboarding.md + _WORK.md（如有），
#    然后按 _WORK.md 的第一个未勾任务继续"
```

---

## 8. Git workflow（按 Ray 最新偏好）

来自 `feedback_git_autonomous.md`（memory）：

- **commit / push / tag 自主执行**，不问
- 一个 logical change 一个 commit；大 feature 可以是"一个 cohesive feature commit + 一个 docs 独立 commit"这种模式（见 v0.6 的两个 commit）
- Commit body 说 **why**，不说 what（diff 自证 what）
- 末尾 `Co-Authored-By: Claude Opus 4 (1M context) <noreply@anthropic.com>`，heredoc 写入
- 结构性改动前打 `vX.Y-pre-<change>-snapshot` tag
- **敏感操作仍然先问**：force push、reset --hard、branch -D、commit 疑似机密文件、推到 `main` 之外的分支
- pre-commit hook 跑 ruff + pytest-fast + wisdom.yaml loads 检查，不要 `--no-verify`
- GitHub push 用 `.ghtoken`（项目根，gitignored）+ inline credential helper（见最近 v0.6 commit 的 push 命令）

---

## 9. 运行时状态检查清单

当 Ray 问"web server 在吗"/"最近跑得怎么样"时：

```bash
# NAS web server
/opt/bin/tmux ls | grep moatlens-web
curl -s http://127.0.0.1:48291/api/status

# API keys 全活？
export MAMBA_ROOT_PREFIX=/volume1/homes/hellolufeng/micromamba
/volume1/homes/hellolufeng/bin/micromamba run -n ytdlp python bin/doctor.py

# 最近 audit 产出
ls -lt data/audits/*/2026-*.json 2>/dev/null | head -5

# 最近成本
tail -5 data/metrics/cost.jsonl 2>/dev/null

# 备份成功了吗
tail -5 logs/backup.log
ls /volume1/homes/hellolufeng/backups/moatlens/
```

对应 **Mac 端**（不用 micromamba、路径不同）：
```bash
cd ~/SynologyDrive/moatlens
source ~/.venvs/moatlens/bin/activate
python bin/doctor.py
ls -lt "$MOATLENS_DATA_DIR/audits/"*/2026-*.json 2>/dev/null | head -5
```

---

## 10. 给接手 Claude 的首次启动 checklist

到这份文档的你（在 Mac 或 NAS）第一件事做这些：

- [ ] 读 **项目 `CLAUDE.md`**（硬约束、架构、workflow 指令）
- [ ] 读 **`docs/adr/000-index.md`** 扫一遍（知道有哪 9 个架构决定）
- [ ] 看 **`_WORK.md`**（项目根）—— 若存在且状态=进行中，从第一个未勾任务继续；若无，等 Ray 下指令
- [ ] `git log --oneline -10` 看最近做了什么（尤其 v0.6 = commit `2372641`）
- [ ] 如果你是 **Mac 端的 Claude**：额外做这几件（见第 7 节）
  - [ ] `git pull --rebase`
  - [ ] 确认 `~/.venvs/moatlens` 存在且激活
  - [ ] 确认 `PYTHONDONTWRITEBYTECODE=1` 和 `MOATLENS_DATA_DIR` env 已 set
  - [ ] 确认 `pre-commit install` 做过（`.git/hooks/pre-commit` 存在）
- [ ] `pytest tests/ -q` 确认 161 tests 全绿（基线健康）
- [ ] **不要**做下面这些"表现欲"动作：
  - ❌ 读一大堆文件建"索引"（ADR 和这份文档已经是索引）
  - ❌ 建议把已决策的事"再考虑一下"（ADR 记录了决定，不要重开）
  - ❌ 发"项目状态全景总结"除非 Ray 明确问（浪费他时间）

开始吧。

---

## 文档维护

- 这份文档是 **git tracked**，两边 Claude 都能 `git pull` 拿到
- 重要的规则变更 / 新的 Ray 偏好发现，更新这里 + 对应 memory 文件
- 每次 Moatlens 大版本升级（vX.Y），至少更新第 1 节和第 4 节的"当前版本"
- 不要把**具体财务持仓**或**会泄露的个人信息**写进来（这文件会推到 GitHub）
