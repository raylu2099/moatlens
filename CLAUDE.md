# Moatlens — project-level instructions

Project-specific rules for Claude Code when working inside this repo.
Overrides the NAS-level `/volume1/homes/hellolufeng/CLAUDE.md` where they conflict.

---

## Product philosophy (hard constraints)

**Do not propose or add:**
- Technical indicators (RSI, SMA, Bollinger, MACD) — value investors don't use them
- Sentiment indicators (VIX term structure, put-call ratio, short interest, fear-greed index)
- Hard stop-loss logic — violates Buffett "falling price = better deal"
- Daily push notifications — violates Munger "activity is the enemy"
- Realtime price alerts, intraday signals
- Technical chart patterns, trend-following
- Short-selling mechanics, options strategies

**Stay within:**
- 8-stage value-investing audit (Buffett / Munger / Marks / Bolton / Graham)
- Fundamental metrics only (ROIC, OE, DCF, moat analysis, management quality)
- Chinese UI chrome, English technical acronyms (see `docs/adr/004-*`)

---

## Architectural invariants (don't break without an ADR)

- **Single-user only.** No auth, no multi-tenant DB. Keys from `.env`.
  Web binds to `127.0.0.1`. See `docs/adr/001-single-user-mode.md`.
- **Filesystem for audit storage.** Not SQLite. See `docs/adr/002-*`.
- **Prompts are data.** Externalized to `prompts/*.md` and `prompts/wisdom.yaml`.
  See `docs/adr/005-*`.
- **Perplexity models:** only `sonar` or `sonar-pro`. Never `sonar-reasoning-pro`,
  never `sonar-deep-research`. Too expensive for our use case.
- **Commit granularity:** one logical change per commit. Big sessions should
  produce multiple commits, not one mega-commit. Always tag `vX-pre-<change>-snapshot`
  before any structural rewrite.
- **Tests are the contract.** 125+ tests protect invariants. New code that
  touches `engine/stages/s5_owner_earnings.py::_dupont` or
  `engine/stages/s6_valuation.py::_dcf_*` must add or extend tests. Never
  delete a numerical regression test to make a change pass.

---

## Where things are

| What | Where |
|---|---|
| 8-stage business logic | `engine/stages/s1_*.py` → `s8_*.py` |
| Orchestrator (knobs: `--only`, `--from`, `--no-claude`, `resume_from`) | `engine/orchestrator.py` |
| API providers (Claude, Perplexity, FD, FRED, yfinance) | `engine/providers/` |
| Prompt loader (mtime-aware cache) | `engine/prompts_loader.py` |
| Wisdom loader + picker | `engine/wisdom.py` |
| Coach commentary (Haiku + rule fallback) | `engine/coach.py` |
| Stream adapter (SSE events) | `engine/stream_adapter.py` |
| **Ask mode** (intent routing → partial stage run → blocks + citations) | `engine/ask.py` + `shared/ask.py` |
| **Claude JSON guardrails** (pydantic contracts for s3/s4/s8) | `engine/guardrails.py` |
| **Structured logging** (JSON to `logs/moatlens.log`) | `shared/logging_setup.py` |
| **Cost metrics** (`data/metrics/cost.jsonl`) | `shared/metrics.py` |
| **Rate limiter** (token-bucket per provider) | `shared/ratelimit.py` |
| CLI entrypoint | `cli/__main__.py` |
| Web app (three-mode landing / chat / ask / portfolio / history / wisdom) | `web/main.py` + `web/diff.py` + `web/templates/` |
| **SSE client** (reconnect + heartbeat) | `web/static/js/sse-client.js` |
| **Theme toggle** (light/dark, localStorage) | `web/static/js/theme.js` |
| **Heroicons** (inline SVG via `data-icon=""`) | `web/static/js/icons.js` |
| Filesystem storage (audits + index + fcntl lock) | `shared/storage.py` |
| Holdings | `shared/holdings.py` |
| Chat sessions | `shared/chat.py` |
| Ask sessions | `shared/ask.py` |
| Config loader | `shared/config.py` |
| Prompt markdown | `prompts/s3_moat.md`, `s4_capital.md`, `s8_inversion.md` |
| Quote library (45 quotes, 15 themes) | `prompts/wisdom.yaml` |
| ADRs (8 key decisions) | `docs/adr/` |
| Migration path (self-use → SaaS) | `docs/migration/v1-path.md` |
| Budget tracking | `BUDGET.md` |
| Backup script (add to cron) | `bin/backup.sh` |

---

## Working with this repo (for future Claude)

### Before making changes
1. **Check `_WORK.md` at project root** — if it exists and status is "进行中" / "in progress",
   read it first. It's a multi-session, multi-machine task handoff file written by a
   previous Claude (possibly on another machine via Synology Drive sync). Continue from
   the first unchecked subtask.
2. Read the relevant ADR(s) in `docs/adr/` — don't undo a documented decision
3. Check `BUDGET.md` if the change adds API calls
4. Check `git log --oneline -10` for recent context
5. If the task is non-trivial (>1 file or >100 lines), use Plan mode

### Multi-task handoff convention (`_WORK.md`)

When the user asks for a multi-step task (≥3 subtasks), **always write/update
`_WORK.md` at project root** as you work. Synology Drive syncs it to the other
machine, so the next Claude session on NAS **or** Mac picks up seamlessly.

Schema:
```markdown
# <task group name>  (<YYYY-MM-DD> 启动 · <machine: NAS | Mac>)

## 状态: 进行中 | 完成 | 中止

- [ ] 1. task description
- [x] 2. done task description
- [ ] 3. ...

## 已完成产物
- commit abc123 (subtask 1)
- file X modified

## 下一步上下文
Short note about where the next Claude should pick up. Key file paths, line
numbers, blockers, API quirks discovered along the way.

## 历史
- 2026-04-19 启动 on NAS by Ray (3/6 done, stopping for today)
- 2026-04-20 resumed on Mac (completed 4-6)
```

Rules:
- Update `_WORK.md` after EACH completed subtask (flip checkbox + append to
  "已完成产物" if relevant)
- When stopping (session ending or handing off), append to "下一步上下文"
  exactly what you were about to do and any gotchas
- When fully done, set `状态: 完成`, add a closing line to 历史
- `_WORK*.md` is gitignored (sensitive notes stay out of git)
- One active `_WORK.md` per project. If starting new work while old is still
  "进行中", either finish old or rename to `_WORK-archive-<date>.md`

### While making changes
- Keep CLI (`python -m cli`) always working — it's the source-of-truth interface
- Don't commit `data/`, `.env`, `.ghtoken`, `__pycache__` (see `.gitignore`)
- When touching prompts, bump the `<!-- version: N -->` marker
- When touching wisdom.yaml, don't change existing IDs (code references them)
- Write tests before or alongside changes, not after

### Before committing
1. `pytest tests/ -q` must be green
2. `ruff check .` no errors
3. If the change touches prompts, note prompt version bump in commit body
4. Commit message body explains **why**, not **what** (diff shows what)
5. One logical change per commit

### After committing
- For structural rewrites, tag: `git tag vX.Y-pre-<change>-snapshot`
- For significant changes, update relevant ADR or create a new one
- Update `BUDGET.md` historical section if end of month

---

## Claude Code workflow specifics

### Memory
The user's auto-memory at `~/.claude/projects/.../memory/project_moatlens.md` is
the persistent context across sessions. Keep it updated with:
- Current version and commit hash
- Recent architectural decisions (with ADR pointers)
- Known constraints (what Ray banned)

### Task tracking
Use TaskCreate/TaskUpdate for multi-phase work. Clean up completed tasks at
session end rather than leaving them accumulating.

### Plan mode
For any change that touches ≥3 files or ≥200 lines, enter Plan mode first.
Get user approval before implementing.

### Subagents
**Allowed:** `Explore` subagent for read-only deep code searches. Low overhead
(spawns, reads, exits). Useful when scope is unclear.

**Disallowed:** daemon-style subagents, anything that persists between calls,
anything requiring additional MCP servers on the NAS. See NAS-level CLAUDE.md
for the underlying constraint.

### Testing
Unit tests live in `tests/` (**144 tests, all green as of v0.5**). Run with:
```bash
export MAMBA_ROOT_PREFIX=/volume1/homes/hellolufeng/micromamba && \
  /volume1/homes/hellolufeng/bin/micromamba run -n ytdlp python -m pytest tests/ -q
```

Quick smoke for web:
```bash
uvicorn web.main:app --host 127.0.0.1 --port 48291
# Then curl /, /api/status, /wisdom, /portfolio
```

### Running on NAS (production-ish)

Current NAS deployment: **tmux session `moatlens-web`**, bound to `0.0.0.0:48291`
(so Mac on same LAN or Tailscale can reach `http://192.168.31.2:48291` or
`http://100.114.1.70:48291`).

Start / restart:
```bash
/opt/bin/tmux kill-session -t moatlens-web 2>/dev/null
/opt/bin/tmux new-session -d -s moatlens-web \
  -c /volume1/homes/hellolufeng/Drive/moatlens \
  "export MAMBA_ROOT_PREFIX=/volume1/homes/hellolufeng/micromamba && \
   exec /volume1/homes/hellolufeng/bin/micromamba run -n ytdlp \
        uvicorn web.main:app --host 0.0.0.0 --port 48291"
# 关键：`-c /volume1/.../moatlens` 必须加，否则 tmux 从别的 cwd 启动，
# uvicorn 找不到 web.main:app，session 立即退出。
```

Check state:
```bash
/opt/bin/tmux ls | grep moatlens-web
curl -s http://127.0.0.1:48291/api/status
/opt/bin/tmux capture-pane -t moatlens-web -p -S -20   # see latest log lines
```

### Running on Mac (from Synology Drive-synced source)

Mac has a bidirectional sync of the entire repo under (typically) `~/SynologyDrive/moatlens/`.
To run locally without polluting NAS state, **always set these two env vars**:

```bash
export PYTHONDONTWRITEBYTECODE=1    # prevents __pycache__ from syncing back
export MOATLENS_DATA_DIR="$HOME/.moatlens/data"   # isolate Mac audits from NAS
```

Then either `./setup.sh` (first time) + `source .venv/bin/activate` + `uvicorn ...`,
or use the one-shot script at `~/bin/moatlens.sh` if created.

See `docs/adr/` for why specific architectural choices were made. See
`project_moatlens.md` in the user's auto-memory for current operational state
(Anthropic key status, latest commit, etc.).

### Git tags (as of 2026-04)

- `v0.1-multi-tenant-snapshot` — original SaaS scaffold (800+ lines of auth/
  crypto/multi-tenant code, deleted in v0.2)
- `v0.3-pre-coach-snapshot` — pre-conversational UX
- `v0.4-pre-fullrefactor-snapshot` — pre-three-card landing + hardening pass

Tags are the safety net. Never `git reset --hard` without confirming a tag
points at what you're about to discard.

---

## Three-month self-evaluation (2026-07-18)

On that date, Ray answers:
1. Have I run an audit every week for the past 12 weeks?
2. Has any audit changed an investment decision I was about to make?
3. Have I mentioned Moatlens to any friend who wanted to try it?

3 yes → follow `docs/migration/v1-path.md`.
2 yes → keep iterating on self-use, re-evaluate in 3 more months.
≤1 yes → accept it's a personal tool, stop treating it as a startup.
