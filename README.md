# Moatlens

> The Buffett / Munger / Howard Marks lens for value investors.
> A personal AI-assisted stock audit tool that forces you to think deeply before you invest.

## Status — single-user mode (v0.2)

This project intentionally runs **just for you**. There is no login, no multi-tenant database,
no public signup page. Keys come from `.env`. The web server binds to `127.0.0.1`.

The multi-tenant SaaS scaffold from v0.1 lives on the
[`v0.1-multi-tenant-snapshot`](https://github.com/raylu2099/moatlens/tree/v0.1-multi-tenant-snapshot)
tag if you ever want to revive it.

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
# edit .env, then:
python bin/doctor.py                   # verify keys and connectivity
python -m cli audit AAPL --tech        # run 8-stage audit
python -m cli diff AAPL                # compare latest vs previous audit
uvicorn web.main:app --host 127.0.0.1 --port 8000
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
