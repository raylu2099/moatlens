"""
AskSession — persistence for the /ask mode.

Minimal structure: one query → one stream → done. Unlike ChatSession which
holds a conversation, AskSession stores: query, ticker, selected stages,
final answer blocks. No multi-turn state.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config import Config


ASK_TTL_DAYS = 7


@dataclass
class AskSession:
    session_id: str
    query: str = ""
    ticker: str = ""
    status: str = "pending"            # pending | routing | running | complete | error
    selected_stages: list[int] = field(default_factory=list)
    intent_rationale: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, query: str, ticker: str) -> "AskSession":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            session_id=uuid.uuid4().hex,
            query=query, ticker=ticker.upper(),
            created_at=now, updated_at=now,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def asks_dir(cfg: Config) -> Path:
    d = cfg.data_dir / "asks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(cfg: Config, session_id: str) -> Path:
    if not session_id.isalnum():
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return asks_dir(cfg) / f"{session_id}.json"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def save_ask_session(cfg: Config, session: AskSession) -> Path:
    session.updated_at = datetime.now(timezone.utc).isoformat()
    path = _session_path(cfg, session.session_id)
    _atomic_write(path, json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
    return path


def load_ask_session(cfg: Config, session_id: str) -> AskSession | None:
    path = _session_path(cfg, session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return AskSession(
        session_id=data.get("session_id", session_id),
        query=data.get("query", ""),
        ticker=data.get("ticker", ""),
        status=data.get("status", "pending"),
        selected_stages=list(data.get("selected_stages") or []),
        intent_rationale=data.get("intent_rationale", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def cleanup_expired(cfg: Config, ttl_days: int = ASK_TTL_DAYS) -> int:
    d = asks_dir(cfg)
    if not d.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    removed = 0
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = data.get("updated_at") or data.get("created_at") or ""
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            p.unlink(missing_ok=True)
            removed += 1
    return removed
