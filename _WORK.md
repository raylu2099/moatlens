# moatlens 维护接力  (2026-06-02 · Mac)

## 状态: 进行中（迁移到 本地克隆 + GitHub 双向接力）

## 架构（重要 — 取代旧的 Synology Drive 同步）
- **Mac 工作副本**: `~/Claude Code/moatlens`（本地盘，不在 Synology Drive 上）
- **NAS**: `/volume1/homes/hellolufeng/Drive/moatlens`（跑 web + 分析师 cron = 生产）
- **同步只走 GitHub**（origin = raylu2099/moatlens，分支 round-3-audit-fixes）：
  - Mac 改完 → `mlpush "msg"`（add -A + commit + push）→ NAS 定时 pull 拿到
  - NAS 改完 → 在 NAS commit + push → Mac 用 `moatlens-env` 进项目时自动 pull 拿到
- **不再用 Synology Drive 同步代码**（文件级同步 `.git` 会 stale-NFS 损坏）。
- `_WORK*.md` 现纳入 git 跟踪（旧的 Drive 交接已停用）。

## 已完成
- 模型修复 `5749552`：Opus 定价 $15/$75→$5/$25（修 bug）+ 型号现代化到 4.6/4.7；全量 pytest 绿（py3.13）
- Mac：本地克隆、venv `~/.venvs/moatlens`(3.13)、`moatlens-env`(进项目自动 pull)、`mlpush`(收尾推送)
- `.gitignore`：`_WORK*` 改为跟踪

## 下一步（NAS 侧，待 Ray）
- [ ] NAS 加定时 `git pull --ff-only origin round-3-audit-fixes`（DSM 任务计划，每 10–15 min）
- [ ] NAS 一次性：`mv _WORK.md _WORK.md.bak` 后 `git pull`（拿到被跟踪的 _WORK.md，再把旧内容并进来）
- [ ] 重开 Synology Drive 时把 `moatlens` 排除出同步
- [ ] 跑通后删 CloudStorage 上旧 `moatlens` 副本

## 历史
- 2026-06-02 Mac：迁出 Synology Drive → 本地克隆 + GitHub 桥接（根治 stale-NFS）
