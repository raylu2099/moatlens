# Moatlens

> The Buffett / Munger / Howard Marks lens for modern value investors.
> An AI-assisted stock audit tool that forces you to think deeply before you invest.

## What is this?

Moatlens runs a **structured 8-stage audit** on any US stock, anchored in the frameworks of Warren Buffett, Charlie Munger, Howard Marks, and Anthony Bolton. Each stage is a fail-fast gate — if the company doesn't pass, you stop and log the reason.

Unlike typical "AI stock pickers" that generate confident buy/sell calls, Moatlens does the opposite: it **slows you down** and forces you to articulate *why* you think this is a great business, what could go wrong, and at what price you'd buy.

## Core philosophy

- **Activity is the enemy of value investing.** — Munger
- **Our favorite holding period is forever.** — Buffett
- **You need correctness AND non-consensus to earn alpha.** — Howard Marks
- **The big money is not in the buying and selling, but in the waiting.** — Buffett

Moatlens is the tool the authors of those quotes would actually use.

## The 8 stages

| # | Stage | What it tests |
|---|---|---|
| 1 | 🗑️ Competence & Trash Bin | ROIC > 15%, Gross Margin > 40%, Interest Cov > 5x, F-score, Z-score |
| 2 | 🔍 Integrity / Lie Detector | Accrual ratio, Capex/Depreciation, Goodwill ratio, OCF vs Net Income |
| 3 | 🏰 Moat Analysis | Brand / Network effects / Switching costs / Scale / Intangibles (tech-adapted) |
| 4 | 👔 Management & Capital Allocation | Buffett's $1 test, buyback discipline, CEO letter candor |
| 5 | 💰 Owner Earnings & Quality | Owner Earnings (SBC-adjusted), FCF margin stability, DuPont decomposition |
| 6 | 🎯 Valuation | DCF + Reverse DCF + Monte Carlo |
| 7 | 🛡️ Margin of Safety & Asymmetry | Intrinsic value × 0.7, Kelly sizing, Howard Marks consensus check |
| 8 | 🔄 Inversion & Variant View | Munger's "invert, always invert" + 9-question Variant View Canvas |

## Architecture

Two frontends share one engine:

```
┌─────────────┐  ┌─────────────┐
│  CLI wizard │  │  Web (BYOK) │
└──────┬──────┘  └──────┬──────┘
       └────────┬───────┘
       ┌───────▼────────┐
       │     engine/    │
       │  8 stages      │
       │  5 providers   │
       │  orchestrator  │
       └────────────────┘
              │
      ┌───────▼────────┐
      │ Users' BYOK    │
      │ API keys       │
      └────────────────┘
```

## Status

🚧 **Pre-alpha / v0.1 in active development.** Not ready for public use yet.

## License

MIT
