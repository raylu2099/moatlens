"""
8-stage audit pipeline.

Stages 1, 2, 4, 5 are rule-based (pure financial math, fast, cheap).
Stages 3, 6, 7, 8 invoke Claude (more expensive, slower, richer analysis).

Each stage:
- Takes context (cfg, keys, ticker, prior stage outputs, raw data bundle)
- Returns StageResult with verdict + metrics + findings + raw_data
- Never mutates global state
"""
