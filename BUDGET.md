# Moatlens API Budget

Tracks monthly API spend goals so Ray's Anthropic / Perplexity / Financial
Datasets bills don't silently balloon. Updated manually at month end.

## Monthly targets

| Service | Target | Hard cap | How measured |
|---|---|---|---|
| Anthropic (Sonnet + Haiku) | $15/mo | $30/mo | `data/metrics/cost.jsonl` aggregated |
| Perplexity (sonar / sonar-pro) | $3/mo | $10/mo | billing dashboard |
| Financial Datasets | $49/mo flat | — | subscription |
| FRED | $0 | $0 | free tier |

**Total monthly target:** ~$70 all-in for Moatlens alone.

Related projects (not in this budget):
- `market-intel` — separate budget in `/volume1/homes/hellolufeng/market-intel/BUDGET.md`
- Ad-hoc Claude experimentation — no budget, tracked via Anthropic console

## Per-audit cost envelope

| Mode | Avg cost | Notes |
|---|---|---|
| Full 8-stage audit (no tech flag) | $0.35 | Sonnet for stages 3/4/8 + Haiku coach |
| Full 8-stage (tech flag) | $0.40 | +SBC perplexity query |
| `--only 6` (just DCF) | $0.01 | no Claude calls |
| `--no-claude` dry-run | $0.00 | Haiku coach disabled via env |
| `/ask` mode | $0.10-0.30 | varies by stages selected |

Worst case observed: ~$0.80 for a tech stock with heavy inversion iteration.

## Observability

Every Claude/Perplexity call writes a line to `data/metrics/cost.jsonl`:
```jsonl
{"ts":"2026-04-18T18:00:00Z","provider":"claude","model":"claude-sonnet-4-5","input_tok":2300,"output_tok":800,"cost_usd":0.0189,"stage":3,"session_id":"..."}
```

Weekly review: `cat data/metrics/cost.jsonl | jq -r 'select(.ts | startswith("2026-04"))|.cost_usd' | awk '{s+=$1}END{print s}'`

## Alerts (manual for now)

When reviewing:
- If weekly total > $10 → investigate loop or repeated retries
- If `--only` ratio vs full audit drops below 20% → I'm running full audits
  too often, should use `--only 6` or `--no-claude` for DCF tuning
- If Haiku cost > 10% of Sonnet cost → coach prompts may be too long

## Historical

| Month | Anthropic actual | Perplexity actual | Notes |
|---|---|---|---|
| 2026-04 | TBD | TBD | Moatlens v0.4 shipped mid-month |

Fill in at each month close.
