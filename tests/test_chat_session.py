"""Chat session persistence + TTL cleanup tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.chat import (
    CHAT_TTL_DAYS, ChatMessage, ChatSession,
    chats_dir, cleanup_expired, delete_session,
    list_sessions, load_session, save_session,
)
from shared.config import Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    data = tmp_path / "data"
    data.mkdir()
    return Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="", pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


def test_new_session_has_hex_id():
    s = ChatSession.new("aapl")
    assert s.session_id.isalnum()
    assert len(s.session_id) == 32
    assert s.ticker == "AAPL"          # uppercased
    assert s.audit_status == "pending"


def test_save_and_load_roundtrip(cfg):
    s = ChatSession.new("AAPL")
    s.anchor_thesis = "生态锁定 + 品牌"
    s.my_variant_view = "AI 护城河深化"
    s.add(ChatMessage.new("user", "我想审视 AAPL"))
    s.add(ChatMessage.new("coach", "好，先告诉我为什么", stage_id=0))
    save_session(cfg, s)

    loaded = load_session(cfg, s.session_id)
    assert loaded is not None
    assert loaded.ticker == "AAPL"
    assert loaded.anchor_thesis == "生态锁定 + 品牌"
    assert loaded.my_variant_view == "AI 护城河深化"
    assert len(loaded.messages) == 2
    assert loaded.messages[0].role == "user"


def test_load_missing_returns_none(cfg):
    assert load_session(cfg, "a" * 32) is None


def test_invalid_session_id_rejected(cfg):
    with pytest.raises(ValueError):
        save_session(cfg, ChatSession(session_id="../../etc/passwd"))


def test_list_sessions_sorted_by_updated_at(cfg):
    a = ChatSession.new("AAPL")
    b = ChatSession.new("NVDA")
    save_session(cfg, a)
    # Force b's updated_at to be newer
    save_session(cfg, b)
    rows = list_sessions(cfg)
    assert [r["ticker"] for r in rows] == ["NVDA", "AAPL"]


def test_delete_session(cfg):
    s = ChatSession.new("AAPL")
    save_session(cfg, s)
    assert delete_session(cfg, s.session_id) is True
    assert load_session(cfg, s.session_id) is None
    assert delete_session(cfg, s.session_id) is False


def test_cleanup_expired(cfg):
    # Fresh session
    fresh = ChatSession.new("AAPL")
    save_session(cfg, fresh)

    # Write an expired one directly
    old = ChatSession.new("NVDA")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=CHAT_TTL_DAYS + 1)).isoformat()
    old.created_at = old_ts
    old.updated_at = old_ts
    path = chats_dir(cfg) / f"{old.session_id}.json"
    path.write_text(
        json.dumps(old.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    removed = cleanup_expired(cfg)
    assert removed == 1
    assert load_session(cfg, fresh.session_id) is not None
    assert load_session(cfg, old.session_id) is None


def test_cleanup_removes_corrupt_files(cfg):
    bad = chats_dir(cfg) / ("a" * 32 + ".json")
    bad.write_text("not valid json {{{{", encoding="utf-8")
    removed = cleanup_expired(cfg)
    assert removed == 1
    assert not bad.exists()


def test_chat_message_timestamp_iso_utc():
    m = ChatMessage.new("user", "hi")
    # Roundtrips as ISO
    datetime.fromisoformat(m.ts)
    assert m.ts.endswith("+00:00")     # timezone.utc suffix
