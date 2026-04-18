"""
Per-user storage layout. Supports both single-user (CLI) and multi-tenant (web).

Paths (CLI mode):
  data/users/local/audits/<TICKER>/<YYYY-MM-DD>.md
  data/users/local/theses/<TICKER>.md
  data/users/local/journal/<YYYY-MM-DD>.md

Paths (web mode):
  data/users/<user_id>/audits/<TICKER>/<YYYY-MM-DD>.md
  ...
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.models import AuditReport
from shared.config import Config


DEFAULT_USER = "local"


def user_dir(cfg: Config, user_id: str = DEFAULT_USER) -> Path:
    d = cfg.data_dir / "users" / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def audits_dir(cfg: Config, ticker: str, user_id: str = DEFAULT_USER) -> Path:
    d = user_dir(cfg, user_id) / "audits" / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def theses_path(cfg: Config, ticker: str, user_id: str = DEFAULT_USER) -> Path:
    d = user_dir(cfg, user_id) / "theses"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{ticker.upper()}.md"


def journal_path(cfg: Config, date_str: str, user_id: str = DEFAULT_USER) -> Path:
    d = user_dir(cfg, user_id) / "journal"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{date_str}.md"


def save_audit(
    cfg: Config,
    report: AuditReport,
    markdown: str,
    user_id: str = DEFAULT_USER,
) -> tuple[Path, Path]:
    """Save both JSON (machine-readable) and MD (human-readable)."""
    base = audits_dir(cfg, report.ticker, user_id) / report.audit_date
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    md_path.write_text(markdown, encoding="utf-8")
    return md_path, json_path


def load_audit(cfg: Config, ticker: str, date: str, user_id: str = DEFAULT_USER) -> AuditReport | None:
    path = audits_dir(cfg, ticker, user_id) / f"{date}.json"
    if not path.exists():
        return None
    return AuditReport.model_validate_json(path.read_text(encoding="utf-8"))


def list_audits(cfg: Config, user_id: str = DEFAULT_USER) -> list[tuple[str, str, Path]]:
    """Return [(ticker, date, md_path), ...] sorted newest first."""
    d = user_dir(cfg, user_id) / "audits"
    if not d.exists():
        return []
    out = []
    for ticker_dir in d.iterdir():
        if not ticker_dir.is_dir():
            continue
        for md_file in ticker_dir.glob("*.md"):
            out.append((ticker_dir.name, md_file.stem, md_file))
    out.sort(key=lambda x: x[1], reverse=True)
    return out
