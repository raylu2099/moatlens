"""
Chat session persistence for the conversational-coach UX.

Each session is one audit conversation. Stored as JSON under
`data/chats/<session_id>.json`. Atomic writes (tempfile + rename).

Sessions older than CHAT_TTL_DAYS (default 7) get cleaned by `cleanup_expired()`.
The web app calls cleanup on startup.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config import Config


CHAT_TTL_DAYS = 7


@dataclass
class ChatMessage:
    role: str                  # "user" | "coach" | "system"
    text: str
    ts: str                    # ISO timestamp
    quote_id: str = ""         # If this message includes a quote
    stage_id: int = 0          # If tied to a specific audit stage

    @classmethod
    def new(cls, role: str, text: str, **extra) -> "ChatMessage":
        return cls(
            role=role, text=text,
            ts=datetime.now(timezone.utc).isoformat(),
            **extra,
        )


@dataclass
class ChatSession:
    session_id: str
    ticker: str = ""
    anchor_thesis: str = ""
    my_market_expectation: str = ""
    my_variant_view: str = ""
    tech_mode: bool = False
    messages: list[ChatMessage] = field(default_factory=list)
    audit_status: str = "pending"       # pending | running | complete | error
    current_stage: int = 0              # 0 = not started, 1..8 = in-progress, 9 = finalized
    report_date: str = ""               # set when audit saved — links to /audit/<t>/<d>
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, ticker: str = "") -> "ChatSession":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            session_id=uuid.uuid4().hex,
            ticker=ticker.upper(),
            created_at=now, updated_at=now,
        )

    def add(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["messages"] = [asdict(m) for m in self.messages]
        return d


# ---------- Persistence ----------

def chats_dir(cfg: Config) -> Path:
    d = cfg.data_dir / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(cfg: Config, session_id: str) -> Path:
    # Guard against path traversal — session_id should always be hex
    if not session_id.isalnum():
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return chats_dir(cfg) / f"{session_id}.json"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def save_session(cfg: Config, session: ChatSession) -> Path:
    session.updated_at = datetime.now(timezone.utc).isoformat()
    path = _session_path(cfg, session.session_id)
    _atomic_write(path, json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
    return path


def load_session(cfg: Config, session_id: str) -> ChatSession | None:
    path = _session_path(cfg, session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    msgs = [ChatMessage(**m) for m in data.get("messages", []) if isinstance(m, dict)]
    return ChatSession(
        session_id=data.get("session_id", session_id),
        ticker=data.get("ticker", ""),
        anchor_thesis=data.get("anchor_thesis", ""),
        my_market_expectation=data.get("my_market_expectation", ""),
        my_variant_view=data.get("my_variant_view", ""),
        tech_mode=bool(data.get("tech_mode", False)),
        messages=msgs,
        audit_status=data.get("audit_status", "pending"),
        current_stage=int(data.get("current_stage", 0)),
        report_date=data.get("report_date", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def list_sessions(cfg: Config, limit: int = 50) -> list[dict]:
    """Return [{session_id, ticker, created_at, audit_status}, ...] newest first."""
    d = chats_dir(cfg)
    rows = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            rows.append({
                "session_id": data.get("session_id", p.stem),
                "ticker": data.get("ticker", ""),
                "audit_status": data.get("audit_status", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except Exception:
            continue
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows[:limit]


def delete_session(cfg: Config, session_id: str) -> bool:
    path = _session_path(cfg, session_id)
    if path.exists():
        path.unlink()
        return True
    return False


def cleanup_expired(cfg: Config, ttl_days: int = CHAT_TTL_DAYS) -> int:
    """Delete sessions older than ttl_days. Returns count removed."""
    d = chats_dir(cfg)
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
            # Corrupt file — remove it
            p.unlink(missing_ok=True)
            removed += 1
    return removed
