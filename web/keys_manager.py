"""
User BYOK key management + testing.
"""
from __future__ import annotations

from shared.config import ApiKeys, Config
from shared.crypto import decrypt_api_key, encrypt_api_key
from shared.db import get_user_api_keys, mark_key_tested, upsert_api_key

from engine.providers import (
    claude as p_claude,
    financial_datasets as p_fd,
    fred as p_fred,
    perplexity as p_pplx,
    yfinance_provider as p_yf,
)


PROVIDERS = ["anthropic", "perplexity", "financial_datasets", "fred"]


def save_user_key(cfg: Config, user_id: int, provider: str, plaintext: str) -> None:
    enc = encrypt_api_key(plaintext, cfg.key_encryption_key)
    upsert_api_key(cfg, user_id, provider, enc)


def load_user_keys(cfg: Config, user_id: int) -> ApiKeys:
    rows = get_user_api_keys(cfg, user_id)
    def dec(provider: str) -> str:
        if provider in rows:
            return decrypt_api_key(rows[provider]["encrypted_key"], cfg.key_encryption_key)
        return ""
    return ApiKeys(
        anthropic=dec("anthropic"),
        perplexity=dec("perplexity"),
        financial_datasets=dec("financial_datasets"),
        fred=dec("fred"),
    )


def test_user_key(cfg: Config, user_id: int, provider: str) -> tuple[bool, str]:
    keys = load_user_keys(cfg, user_id)
    if provider == "anthropic":
        ok, msg = p_claude.test_connection(keys)
    elif provider == "perplexity":
        ok, msg = p_pplx.test_connection(keys)
    elif provider == "financial_datasets":
        ok, msg = p_fd.test_connection(keys)
    elif provider == "fred":
        ok, msg = p_fred.test_connection(keys)
    else:
        return False, f"Unknown provider: {provider}"
    mark_key_tested(cfg, user_id, provider, ok, msg)
    return ok, msg


def get_key_statuses(cfg: Config, user_id: int) -> dict:
    """Return {provider: {has_key, masked, last_tested, test_ok, test_message}}"""
    from shared.crypto import mask_key
    rows = get_user_api_keys(cfg, user_id)
    out = {}
    for p in PROVIDERS:
        row = rows.get(p)
        if row:
            plain = decrypt_api_key(row["encrypted_key"], cfg.key_encryption_key)
            out[p] = {
                "has_key": True,
                "masked": mask_key(plain),
                "last_tested": row.get("last_tested_at"),
                "test_ok": bool(row.get("test_ok")),
                "test_message": row.get("test_message", ""),
            }
        else:
            out[p] = {"has_key": False}
    return out
