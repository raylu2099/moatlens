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
from datetime import UTC, datetime, timedelta
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
            "ts": datetime.now(UTC).isoformat(),
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


def today_cost_utc(cfg: Config) -> float:
    """Sum cost_usd for today (UTC). Convenience wrapper for the audit
    start budget guard — keeping the threshold in wall-clock UTC matches
    how cost.jsonl timestamps are stored."""
    today_iso = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00+00:00")
    return total_cost(cfg, since_iso=today_iso)


def archive_cost_log(cfg: Config, keep_days: int = 90) -> tuple[int, int]:
    """Move entries older than `keep_days` from cost.jsonl to a monthly
    archive (`cost-<YYYY-MM>.jsonl`) under `data/metrics/archive/`.

    Append-only growth on cost.jsonl is slow but monotonic; after a few
    years `total_cost()` becomes O(N) drag on every audit's budget check.
    This helper keeps the live file trimmed to the rolling 90-day window
    while preserving full history in archives.

    Returns (entries_archived, entries_kept). Safe to call from cron;
    uses a tempfile + atomic rename for the trimmed live file so a mid-
    run crash can't corrupt the budget view.
    """
    p = cost_log_path(cfg)
    if not p.exists():
        return 0, 0
    cutoff = (datetime.now(UTC) - timedelta(days=keep_days)).isoformat()

    kept: list[str] = []
    by_month: dict[str, list[str]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = e.get("ts") or ""
        except Exception:
            # Keep malformed lines in the live file rather than losing them
            kept.append(line)
            continue
        if ts >= cutoff:
            kept.append(line)
        else:
            month = ts[:7] if len(ts) >= 7 else "unknown"
            by_month.setdefault(month, []).append(line)

    if not by_month:
        return 0, len(kept)

    # Write archives
    archive_dir = metrics_dir(cfg) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    for month, lines in by_month.items():
        apath = archive_dir / f"cost-{month}.jsonl"
        with apath.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
                archived += 1

    # Atomically replace the live log with just the kept-window entries
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    tmp.replace(p)
    return archived, len(kept)
