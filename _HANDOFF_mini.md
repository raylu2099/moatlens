# _HANDOFF_mini.md — Mac mini (ray-mini)

## 角色 (2026-06-14 接手)
- Mac mini 接替**已退役的 MacBook**,成为**主开发机**。NAS 仍是**唯一执行机**(流水线/cron/Telegram);
  mini **绝不另起定时**(防双跑 / 双倍 Max 额度 / 数据打架)。执行态以 `_HANDOFF_nas.md` 为准。
- 身份 `ray-mini <ray@xuedinge.cc>`;工作树在本机本地盘 `~/projects/`(非 Synology 同步盘)。
- 本机已就绪:sing-box 自治翻墙(headless)+ claude 远程控制(经 sing-box,127.0.0.1:7890 守门)+ 爬虫工具(Playwright / trafilatura / feedparser)。

## 已读交接
- 已读 `_HANDOFF_nas.md`(NAS 执行态 + 在途坑)与退役前的 `_HANDOFF_mac.md`(继承开发上下文)。
- 当前无进行中 `_WORK.md`。
- 遵守 CLAUDE.md 三铁律:① 写进持久产物前先核实 git/file/API 状态;② 不自改 `.claude/settings` 放权;③「你决定」= 出草案待确认。

## 下一步上下文
- 等 Ray 指派任务。首个动作:以主开发身份过一遍 `DESIGN.md` + 在途项,提「下一步该做什么」草案。
- 本 PR 另把 `_WORK.md` 纳入 git 跟踪(`!_WORK.md`):Synology Drive 已停用,进行中任务状态需经 git 跨机同步(NAS 留意)。

## 历史
- 2026-06-14 mini 入队、接替退役的 Mac 成为主开发机 (on Mac mini)
