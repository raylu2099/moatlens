# Moatlens

> The Buffett / Munger / Howard Marks lens for value investors.
> A personal AI-assisted stock audit tool that forces you to think deeply before you invest.

## Status — single-user, 对话教练模式 (v0.4)

This project intentionally runs **just for you**. No login, no multi-tenant database.
Keys come from `.env`. Web server binds to `127.0.0.1`.

**v0.4 highlights:**
- **Conversational coach UX** — `/` is a single chat box; the coach streams stage results + master quotes as it runs
- **Wisdom library** — `/wisdom` hosts 45 curated quotes from Buffett / Munger / Marks / Bolton / Graham / Lynch / Klarman / Taleb, in Chinese + English, with sources
- **Context-aware quotes** — each stage ends with a topic-matched quote; decision points (low margin-of-safety, stale thesis, etc.) trigger reminders
- CLI (`python -m cli audit TICKER`) works unchanged

Git tags for snapshot history:
- `v0.1-multi-tenant-snapshot` — original SaaS scaffold
- `v0.3-pre-coach-snapshot` — pre-chat single-user v0.3

## What it does

Runs a **structured 8-stage audit** on any US stock, anchored in the frameworks of Warren Buffett,
Charlie Munger, Howard Marks, and Anthony Bolton. Unlike "AI stock pickers", Moatlens **slows you
down** and forces you to articulate why you think this is a great business, what could go wrong,
and at what price you'd buy.

## The 8 stages

| # | Stage | What it tests |
|---|---|---|
| 1 | 🗑️ Competence & Trash Bin | ROIC > 15%, GM > 40%, Interest Cov > 5x, F-score, Z-score |
| 2 | 🔍 Integrity / Lie Detector | Accrual ratio, Capex/Depreciation, Goodwill ratio, OCF vs Net Income |
| 3 | 🏰 Moat Analysis | Brand / Network / Switching / Scale / Intangibles (Claude) |
| 4 | 👔 Management & Capital Allocation | $1 test, buyback discipline, CEO letter candor (Claude) |
| 5 | 💰 Owner Earnings & Quality | OE (SBC-adjusted), FCF margin stability, DuPont |
| 6 | 🎯 Valuation | DCF + Reverse DCF + Monte Carlo |
| 7 | 🛡️ Margin of Safety & Asymmetry | IV × 0.7, Kelly sizing, Howard Marks check |
| 8 | 🔄 Inversion & Variant View | Munger "invert, always invert" (Claude) |

## Quick start

```bash
./setup.sh                             # creates venv, installs deps, copies .env.example
# edit .env with your ANTHROPIC_API_KEY / PERPLEXITY_API_KEY / FINANCIAL_DATASETS_API_KEY
python bin/doctor.py                   # verify keys + connectivity

# CLI
python -m cli audit AAPL --tech        # full audit
python -m cli audit AAPL --only 6      # re-run just Stage 6 (DCF tuning)
python -m cli audit AAPL --no-claude   # zero-cost dry run (skip stages 3/4/8)
python -m cli diff AAPL                # compare latest vs previous
python -m cli hold add AAPL --size 5%  # track as holding

# Web — 对话教练
uvicorn web.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/ 在对话框输入 ticker
# 浏览语录库: http://127.0.0.1:8000/wisdom
```

## What's in the box

```
moatlens/
├── engine/          # 8 stages, 5 providers, orchestrator
│   ├── stages/      # s1–s8, each independently runnable
│   ├── providers/   # claude, perplexity, financial_datasets, fred, yfinance
│   └── orchestrator.py
├── cli/             # typer + rich wizard (main frontend)
├── web/             # FastAPI, single-user, 127.0.0.1
├── prompts/         # Externalized Claude prompts (s3/s4/s8)
├── shared/          # config + filesystem storage
├── tests/           # numerical regression tests (stage 5/6)
├── docs/concepts/   # learn pages
└── data/audits/     # your audit history (markdown + JSON)
```

## Data provenance

| Source | Use | Required? |
|---|---|---|
| Anthropic (Claude Sonnet-4-5) | Stages 3, 4, 8 qualitative | ✅ |
| Perplexity (sonar-pro) | Recent news / channel checks | ✅ |
| Financial Datasets | Statements, insider trades | ✅ |
| yfinance | Prices, multiples (free) | auto |
| FRED | Risk-free rate (WACC) | optional |

Typical audit cost: **$0.30–$0.80** per ticker.

## Philosophy (guardrails for future you)

- **No technical indicators** (RSI/SMA/Bollinger) — value investors don't care.
- **No sentiment indicators** (VIX term structure, put-call, short interest).
- **No hard stop-loss logic** — violates Buffett's "lower price = better deal".
- **No daily push notifications** — "activity is the enemy of value investing" (Munger).
- **Prompts are externalized** under `prompts/` so you can version them alongside audits.

## License

MIT — but this is primarily a personal tool. Use at your own risk. Not investment advice.
