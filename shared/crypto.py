"""
API key encryption for web multi-tenant storage.
Uses Fernet (AES-128-CBC + HMAC-SHA256) from cryptography library.

Keys are NEVER stored in plaintext in DB or logs.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_fernet_key(passphrase: str) -> bytes:
    """Derive a URL-safe Fernet key from a human passphrase."""
    h = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(h)


def encrypt_api_key(plaintext: str, passphrase: str) -> str:
    if not plaintext:
        return ""
    f = Fernet(_derive_fernet_key(passphrase))
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str, passphrase: str) -> str:
    if not ciphertext:
        return ""
    try:
        f = Fernet(_derive_fernet_key(passphrase))
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def mask_key(key: str) -> str:
    """For display: 'sk-abc...xyz' — never show full key."""
    if not key or len(key) < 12:
        return "***"
    return f"{key[:6]}...{key[-4:]}"
