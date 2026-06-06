# _HANDOFF_mac.md — Mac → NAS 接力(**tracked,跨机**)

> **协议(两机都守 · 2026-06-06 立)**:
> 1. **开工前先 `git pull`**(Mac:`moatlens-env` 会自动 pull;NAS:在其本地克隆里 pull)。
> 2. **只写自己这台**的 handoff:Mac 改 `_HANDOFF_mac.md`,NAS 改 `_HANDOFF_nas.md`,**各写各的、读对方的 = 零合并冲突**(单写者所有权)。
> 3. 详细工作记忆放各自本地 `_WORK.md`(gitignored,不跨机);**跨机要让对方知道的**写这里,简短。
> 4. 架构决策在 `docs/adr/`(tracked,跨机都看得到)。
> 5. SessionStart 钩子(`.claude/hooks/session-start.sh`,进仓)会自动把 `_WORK.md` + 本文件 + `_HANDOFF_nas.md` 注入会话开头 → 你一开 Claude 就看到两机状态。

---

## Mac 最新(2026-06-06 · 交接机制升级)

**架构(取代旧的 Synology Drive 同步)**:
- **Mac 工作副本**:`~/Claude Code/moatlens`(本地盘,不在 Synology Drive 上)。进出用 `moatlens-env`(自动 pull)/ `mlpush`(收尾推送)。
- **NAS**:`/volume1/homes/hellolufeng/Drive/moatlens`(跑 web + 分析师 cron = 生产)。
- **同步只走 GitHub**(origin = `git@github.com:raylu2099/moatlens.git`;主用分支 `round-3-audit-fixes`)。
- **不再用 Synology Drive 同步代码**(文件级同步 `.git` 会 stale-NFS 损坏)。

**2026-06-06 本轮改动(Mac · 加固跨机交接)**:
- 同步 remote 已 **HTTPS → SSH 免密** ✓。
- **交接机制从"共享单 `_WORK.md`"升级为"分体 handoff"**(本提交)✓:`_WORK.md` 改回本地 gitignored;新增 tracked 的 `_HANDOFF_mac.md` / `_HANDOFF_nas.md`,各机单写 → 根除双写 git 合并冲突。照搬 signal-radar 已验证的同款设计。
- 新增**项目级 SessionStart 钩子**(`.claude/`,进仓)→ NAS 一 pull 就自动有,开 Claude 即注入两机状态。
- 修了 CLAUDE.md 过时说法(原同时写着 "_WORK*.md is gitignored" 与 "is now git-tracked",自相矛盾)。
- **本会话稍后**:把 `round-3-audit-fixes`(领先 main 34 提交)FF 合并进 `main`,防 main 腐化;NAS 仍拉 `round-3-audit-fixes`,两分支暂指同一提交。

**给 NAS 的待办**:见 `_HANDOFF_nas.md`(我已把旧 `_WORK.md` 里的 NAS 侧 todo 种进去,NAS 接手后由你维护那个文件)。
