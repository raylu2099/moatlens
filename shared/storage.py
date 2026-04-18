"""
Single-user filesystem storage.

Layout:
  data/audits/<TICKER>/<YYYY-MM-DD>.md      human-readable report
  data/audits/<TICKER>/<YYYY-MM-DD>.json    machine-readable AuditReport

No database. No users. Scanning the filesystem is fast enough for personal use
(hundreds of audits is still milliseconds).
"""
from __future__ import annotations

from pathlib import Path

from engine.models import AuditReport
from shared.config import Config


def audits_root(cfg: Config) -> Path:
    d = cfg.data_dir / "audits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audits_dir(cfg: Config, ticker: str) -> Path:
    d = audits_root(cfg) / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_audit(
    cfg: Config, report: AuditReport, markdown: str,
) -> tuple[Path, Path]:
    base = audits_dir(cfg, report.ticker) / report.audit_date
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return md_path, json_path


def load_audit(cfg: Config, ticker: str, date: str) -> AuditReport | None:
    path = audits_dir(cfg, ticker) / f"{date}.json"
    if not path.exists():
        return None
    return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))


def list_audits(cfg: Config) -> list[dict]:
    """Return [{ticker, audit_date, md_path, action, confidence, cost}, ...] newest first."""
    root = audits_root(cfg)
    if not root.exists():
        return []
    out = []
    for ticker_dir in root.iterdir():
        if not ticker_dir.is_dir():
            continue
        for json_file in ticker_dir.glob("*.json"):
            date = json_file.stem
            md_path = json_file.with_suffix(".md")
            # Lightweight parse — we only need a few fields for the listing.
            action = ""
            confidence = ""
            cost = 0.0
            try:
                import json as _json
                data = _json.loads(json_file.read_text(encoding="utf-8"))
                action = (data.get("overall_action") or "") or ""
                confidence = (data.get("overall_confidence") or "") or ""
                cost = float(data.get("total_api_cost_usd") or 0)
            except Exception:
                pass
            out.append({
                "ticker": ticker_dir.name,
                "audit_date": date,
                "md_path": md_path,
                "json_path": json_file,
                "action": action,
                "confidence": confidence,
                "total_cost_usd": cost,
            })
    out.sort(key=lambda x: x["audit_date"], reverse=True)
    return out


def list_audit_dates_for_ticker(cfg: Config, ticker: str) -> list[str]:
    """Return audit dates for a ticker, newest first."""
    d = audits_dir(cfg, ticker)
    dates = sorted({p.stem for p in d.glob("*.json")}, reverse=True)
    return dates


def load_last_two_audits(cfg: Config, ticker: str) -> tuple[AuditReport | None, AuditReport | None]:
    """Return (current, previous) — previous is None if only one audit exists."""
    dates = list_audit_dates_for_ticker(cfg, ticker)
    current = load_audit(cfg, ticker, dates[0]) if dates else None
    previous = load_audit(cfg, ticker, dates[1]) if len(dates) >= 2 else None
    return current, previous
