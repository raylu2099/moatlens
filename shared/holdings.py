"""
Simple JSON-backed holdings tracker.

Schema: data/holdings.json
[
  {"ticker": "AAPL", "size": "5%", "added_at": "2026-04-18", "note": "core"},
  ...
]

Atomic writes via tempfile + rename so a Ctrl+C mid-write doesn't corrupt the file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from shared.config import Config


def holdings_path(cfg: Config) -> Path:
    return cfg.data_dir / "holdings.json"


def load_holdings(cfg: Config) -> list[dict]:
    p = holdings_path(cfg)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [h for h in data if isinstance(h, dict) and h.get("ticker")]
    except Exception:
        pass
    return []


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def save_holdings(cfg: Config, holdings: list[dict]) -> None:
    p = holdings_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(holdings, indent=2, ensure_ascii=False))


def add_holding(
    cfg: Config, ticker: str, size: str = "", note: str = "",
) -> dict:
    ticker = ticker.strip().upper()
    hs = load_holdings(cfg)
    # Upsert
    for h in hs:
        if h["ticker"] == ticker:
            if size:
                h["size"] = size
            if note:
                h["note"] = note
            h["updated_at"] = datetime.now().strftime("%Y-%m-%d")
            save_holdings(cfg, hs)
            return h
    new = {
        "ticker": ticker,
        "size": size,
        "note": note,
        "added_at": datetime.now().strftime("%Y-%m-%d"),
    }
    hs.append(new)
    save_holdings(cfg, hs)
    return new


def remove_holding(cfg: Config, ticker: str) -> bool:
    ticker = ticker.strip().upper()
    hs = load_holdings(cfg)
    new = [h for h in hs if h["ticker"] != ticker]
    if len(new) == len(hs):
        return False
    save_holdings(cfg, new)
    return True


def is_holding(cfg: Config, ticker: str) -> bool:
    ticker = ticker.strip().upper()
    return any(h["ticker"] == ticker for h in load_holdings(cfg))
