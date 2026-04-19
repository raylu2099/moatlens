"""
Single-user filesystem storage.

Layout:
  data/audits/_index.json             fast lookup table (updated on save)
  data/audits/<TICKER>/<YYYY-MM-DD>.md      human-readable report
  data/audits/<TICKER>/<YYYY-MM-DD>.json    machine-readable AuditReport

The index lets list_audits() return in O(1) reads instead of O(N) full JSON parses.
It's a cache — if it goes missing or stale, list_audits() falls back to a full scan
and rebuilds it. You can always delete the index to force a rebuild.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from engine.models import AuditReport
from shared.config import Config


INDEX_FILENAME = "_index.json"


@contextmanager
def _index_lock(cfg: Config):
    """Advisory POSIX flock on the index file — serializes concurrent save_audit."""
    p = _index_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Use a dedicated lockfile so the actual index can be replaced atomically
    lock_path = p.with_suffix(p.suffix + ".lock")
    with open(lock_path, "w") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def audits_root(cfg: Config) -> Path:
    d = cfg.data_dir / "audits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audits_dir(cfg: Config, ticker: str) -> Path:
    d = audits_root(cfg) / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(cfg: Config) -> Path:
    return audits_root(cfg) / INDEX_FILENAME


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _row_from_report(report: AuditReport, md_path: Path, json_path: Path) -> dict:
    return {
        "ticker": report.ticker,
        "audit_date": report.audit_date,
        "action": report.overall_action.value if report.overall_action else "",
        "confidence": report.overall_confidence.value if report.overall_confidence else "",
        "total_cost_usd": float(report.total_api_cost_usd or 0),
        "md_path": str(md_path),
        "json_path": str(json_path),
    }


def save_audit(
    cfg: Config, report: AuditReport, markdown: str,
) -> tuple[Path, Path]:
    base = audits_dir(cfg, report.ticker) / report.audit_date
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    _atomic_write(json_path, report.model_dump_json(indent=2))
    _atomic_write(md_path, markdown)

    # Update index incrementally under flock — protects against concurrent
    # save_audit (e.g. Ray's CLI finishing one audit while web does another)
    with _index_lock(cfg):
        index = _load_index_raw(cfg)
        key = (report.ticker, report.audit_date)
        index = [r for r in index if (r["ticker"], r["audit_date"]) != key]
        index.append(_row_from_report(report, md_path, json_path))
        index.sort(key=lambda r: r["audit_date"], reverse=True)
        _atomic_write(_index_path(cfg), json.dumps(index, indent=2, ensure_ascii=False))

    return md_path, json_path


def load_audit(cfg: Config, ticker: str, date_str: str) -> AuditReport | None:
    path = audits_dir(cfg, ticker) / f"{date_str}.json"
    if not path.exists():
        return None
    return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))


def _load_index_raw(cfg: Config) -> list[dict]:
    p = _index_path(cfg)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _full_scan(cfg: Config) -> list[dict]:
    """Rebuild the index by scanning every audit JSON — slow path."""
    root = audits_root(cfg)
    rows: list[dict] = []
    for ticker_dir in root.iterdir():
        if not ticker_dir.is_dir():
            continue
        for json_file in ticker_dir.glob("*.json"):
            date_str = json_file.stem
            md_path = json_file.with_suffix(".md")
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append({
                "ticker": ticker_dir.name,
                "audit_date": date_str,
                "action": data.get("overall_action") or "",
                "confidence": data.get("overall_confidence") or "",
                "total_cost_usd": float(data.get("total_api_cost_usd") or 0),
                "md_path": str(md_path),
                "json_path": str(json_file),
            })
    rows.sort(key=lambda r: r["audit_date"], reverse=True)
    return rows


def rebuild_index(cfg: Config) -> list[dict]:
    """Force a full scan and rewrite the index."""
    rows = _full_scan(cfg)
    _atomic_write(_index_path(cfg), json.dumps(rows, indent=2, ensure_ascii=False))
    return rows


def _decorate_age(rows: list[dict]) -> list[dict]:
    today = date.today()
    out = []
    for r in rows:
        age_days = None
        try:
            age_days = (today - date.fromisoformat(r["audit_date"])).days
        except Exception:
            pass
        stale_level = "fresh"
        if age_days is not None:
            if age_days >= 180:
                stale_level = "very_stale"
            elif age_days >= 90:
                stale_level = "stale"
        out.append({**r, "age_days": age_days, "stale_level": stale_level})
    return out


def list_audits(cfg: Config) -> list[dict]:
    """Return newest-first [{ticker, audit_date, action, confidence, total_cost_usd, age_days, stale_level, ...}, ...]."""
    root = audits_root(cfg)
    if not root.exists():
        return []
    rows = _load_index_raw(cfg)
    if not rows:
        rows = rebuild_index(cfg)
    else:
        # Sanity: index should not claim a json that was deleted.
        valid = [r for r in rows if Path(r.get("json_path", "")).exists()]
        if len(valid) != len(rows):
            rows = rebuild_index(cfg)
    return _decorate_age(rows)


def list_audit_dates_for_ticker(cfg: Config, ticker: str) -> list[str]:
    """Return audit dates for a ticker, newest first."""
    d = audits_dir(cfg, ticker)
    dates = sorted({p.stem for p in d.glob("*.json")}, reverse=True)
    return dates


def load_last_two_audits(
    cfg: Config, ticker: str,
) -> tuple[AuditReport | None, AuditReport | None]:
    """Return (current, previous) — previous is None if only one audit exists."""
    dates = list_audit_dates_for_ticker(cfg, ticker)
    current = load_audit(cfg, ticker, dates[0]) if dates else None
    previous = load_audit(cfg, ticker, dates[1]) if len(dates) >= 2 else None
    return current, previous
