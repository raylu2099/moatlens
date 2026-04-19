"""
Append-only cost/metrics log.

Every API call writes a JSON line to data/metrics/cost.jsonl. Used by:
- BUDGET.md weekly reviews
- Future dashboards
- Debugging "why did this audit cost $2?"

Schema per line:
{
  "ts": "2026-04-18T18:00:00+00:00",
  "provider": "claude" | "perplexity" | "financial_datasets",
  "model": "claude-sonnet-4-5" | null,
  "input_tok": 2300, "output_tok": 800,
  "cost_usd": 0.0189,
  "stage": 3 | null,
  "session_id": "..." | null,
  "ticker": "AAPL" | null,
  "tag": "audit" | "coach" | "ask_routing" | ...
}

Designed to be safe under concurrent writes (append-only, no rewrite).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.config import Config


def metrics_dir(cfg: Config) -> Path:
    d = cfg.data_dir / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cost_log_path(cfg: Config) -> Path:
    return metrics_dir(cfg) / "cost.jsonl"


def log_cost(
    cfg: Config,
    *,
    provider: str,
    cost_usd: float,
    model: str | None = None,
    input_tok: int | None = None,
    output_tok: int | None = None,
    stage: int | None = None,
    session_id: str | None = None,
    ticker: str | None = None,
    tag: str = "",
) -> None:
    """Append one cost event. Errors here must never propagate."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "input_tok": input_tok,
            "output_tok": output_tok,
            "cost_usd": round(float(cost_usd or 0), 6),
            "stage": stage,
            "session_id": session_id,
            "ticker": ticker,
            "tag": tag,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        # Append-mode open does atomic writes on POSIX for small lines
        with cost_log_path(cfg).open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Metrics logging failures must NEVER break an audit.
        pass


def read_cost_entries(cfg: Config) -> list[dict]:
    """Read all cost entries. For weekly summaries / tests."""
    p = cost_log_path(cfg)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def total_cost(cfg: Config, since_iso: str | None = None) -> float:
    """Sum cost_usd over all entries (or since an ISO timestamp)."""
    entries = read_cost_entries(cfg)
    if since_iso:
        entries = [e for e in entries if (e.get("ts") or "") >= since_iso]
    return sum(float(e.get("cost_usd") or 0) for e in entries)
