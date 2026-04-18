"""
SQLite database layer for multi-tenant web mode.
Schema kept minimal — filesystem still holds audit markdown/json.

Tables:
- users: email, password_hash, created_at
- api_keys: user_id, provider, encrypted_key (Fernet), created_at, last_tested_at, test_ok
- audit_index: user_id, ticker, date, file_path, action (for fast listing)
- shared_reports: slug, user_id, ticker, date, public (for SEO share pages)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from shared.config import Config


def db_path(cfg: Config) -> Path:
    return cfg.data_dir / "moatlens.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_keys (
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    last_tested_at TIMESTAMP,
    test_ok INTEGER DEFAULT 0,
    test_message TEXT DEFAULT '',
    PRIMARY KEY (user_id, provider),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    audit_date TEXT NOT NULL,
    file_path TEXT NOT NULL,
    action TEXT DEFAULT '',
    confidence TEXT DEFAULT '',
    total_cost_usd REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, ticker, audit_date)
);
CREATE INDEX IF NOT EXISTS idx_audit_user_ticker ON audit_index(user_id, ticker);

CREATE TABLE IF NOT EXISTS shared_reports (
    slug TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    audit_date TEXT NOT NULL,
    public INTEGER DEFAULT 1,
    views INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shared_ticker ON shared_reports(ticker);
"""


def init_db(cfg: Config) -> None:
    path = db_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


@contextmanager
def get_conn(cfg: Config):
    conn = sqlite3.connect(str(db_path(cfg)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- User operations ---

def create_user(cfg: Config, email: str, password_hash: str, display_name: str = "") -> int:
    with get_conn(cfg) as c:
        cur = c.execute(
            "INSERT INTO users(email, password_hash, display_name) VALUES (?, ?, ?)",
            (email.lower(), password_hash, display_name),
        )
        return cur.lastrowid


def get_user_by_email(cfg: Config, email: str) -> dict | None:
    with get_conn(cfg) as c:
        row = c.execute(
            "SELECT id, email, password_hash, display_name FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(cfg: Config, user_id: int) -> dict | None:
    with get_conn(cfg) as c:
        row = c.execute(
            "SELECT id, email, display_name FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


# --- API key operations ---

def upsert_api_key(
    cfg: Config, user_id: int, provider: str, encrypted_key: str,
) -> None:
    with get_conn(cfg) as c:
        c.execute(
            """INSERT INTO api_keys(user_id, provider, encrypted_key)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET encrypted_key = excluded.encrypted_key""",
            (user_id, provider, encrypted_key),
        )


def get_user_api_keys(cfg: Config, user_id: int) -> dict[str, dict]:
    """Return {provider: {encrypted_key, test_ok, test_message, last_tested_at}}"""
    with get_conn(cfg) as c:
        rows = c.execute(
            "SELECT provider, encrypted_key, test_ok, test_message, last_tested_at FROM api_keys WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {r["provider"]: dict(r) for r in rows}


def mark_key_tested(
    cfg: Config, user_id: int, provider: str, ok: bool, message: str,
) -> None:
    with get_conn(cfg) as c:
        c.execute(
            """UPDATE api_keys SET test_ok = ?, test_message = ?, last_tested_at = CURRENT_TIMESTAMP
               WHERE user_id = ? AND provider = ?""",
            (1 if ok else 0, message, user_id, provider),
        )


def delete_api_key(cfg: Config, user_id: int, provider: str) -> None:
    with get_conn(cfg) as c:
        c.execute(
            "DELETE FROM api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        )


# --- Audit index ---

def index_audit(
    cfg: Config, user_id: int, ticker: str, date: str,
    file_path: str, action: str, confidence: str, cost: float,
) -> None:
    with get_conn(cfg) as c:
        c.execute(
            """INSERT INTO audit_index(user_id, ticker, audit_date, file_path, action, confidence, total_cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, ticker, audit_date) DO UPDATE SET
                 file_path = excluded.file_path,
                 action = excluded.action,
                 confidence = excluded.confidence,
                 total_cost_usd = excluded.total_cost_usd""",
            (user_id, ticker.upper(), date, file_path, action, confidence, cost),
        )


def list_user_audits(cfg: Config, user_id: int, limit: int = 50) -> list[dict]:
    with get_conn(cfg) as c:
        rows = c.execute(
            """SELECT ticker, audit_date, action, confidence, total_cost_usd, created_at
               FROM audit_index WHERE user_id = ? ORDER BY audit_date DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# --- Shared reports ---

def share_report(cfg: Config, user_id: int, ticker: str, date: str, slug: str) -> None:
    with get_conn(cfg) as c:
        c.execute(
            """INSERT INTO shared_reports(slug, user_id, ticker, audit_date)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(slug) DO NOTHING""",
            (slug, user_id, ticker.upper(), date),
        )


def get_shared_report(cfg: Config, slug: str) -> dict | None:
    with get_conn(cfg) as c:
        row = c.execute(
            "SELECT slug, user_id, ticker, audit_date, public, views FROM shared_reports WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row:
            c.execute("UPDATE shared_reports SET views = views + 1 WHERE slug = ?", (slug,))
    return dict(row) if row else None
