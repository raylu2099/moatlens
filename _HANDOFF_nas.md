# _HANDOFF_nas.md — NAS → Mac 接力(**tracked,跨机**)

> 协议见 `_HANDOFF_mac.md` 顶部。**只有 NAS 这台写本文件**;Mac 只读它。开工前先 `git pull`,写完 `git commit` + `git push`。

---

## (Mac 初始化种子 · 2026-06-06 — 待 NAS 接手后改由 NAS 维护)

NAS 还没在新"分体 handoff"机制下写过本文件。以下是从旧 `_WORK.md` 迁来的 **NAS 侧待办**,NAS 接手时处理并改写本文件:

- [ ] NAS 加定时 `git pull --ff-only origin round-3-audit-fixes`(DSM 任务计划,每 10–15 min)。
- [ ] 旧 `_WORK.md` 现已改为 gitignored(本地)。NAS 的私有工作记忆请写本地 `_WORK.md`,跨机要说的写本文件。`git pull` 不会因本地 `_WORK.md` 冲突(已不跟踪)。
- [ ] 重开 Synology Drive 时把 `moatlens` 排除出同步。
- [ ] 跑通后删 CloudStorage 上旧 `moatlens` 副本。

**NAS 接手后请把本段替换成 NAS 自查结果**(参照 signal-radar `_HANDOFF_nas.md` 的格式:remote / 工作树路径是否在同步盘内 / 凭据 / Claude CLI / 定时任务状态)。
