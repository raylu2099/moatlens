# ADR 003 — Drop BYOK, use `.env` directly

**Status:** Accepted
**Date:** 2026-04-18
**Supersedes:** v0.1's BYOK + per-user encrypted key storage

## Context

v0.1 required every user to enter Anthropic + Perplexity + Financial Datasets
API keys via the web UI. Keys were encrypted (Fernet) and stored per-user in
the DB. This was intended to be the product's commercial model (zero API cost
to operator).

## Decision

Drop BYOK. Ray's three keys live in `.env`. CLI and web read the same file.
No per-user storage, no encryption layer.

## Why (funnel analysis)

Measured/estimated conversion through the BYOK gate, per step:
- Visit landing → sign up: ~50% (typical SaaS)
- Sign up → go to settings: ~90%
- Sign up 3 separate accounts (Anthropic + Perplexity + FD): ~60%
- Each paid signup is a credit-card gate: ~60%
- Paste three keys into the form: ~80%

Multiplied: **~14% activation**, and the survivors are developers who'd
prefer to clone the repo anyway.

More importantly: the v0.1 KDF was **broken** (plain SHA256 without salt) —
all users' keys decryptable from a single leaked `SECRET_KEY`. Fixing it
properly requires PBKDF2/scrypt + per-user salt + careful key rotation: weeks
of work for a feature with 14% take-up.

## Consequences

**Positive:**
- One less class of security bug (no secret-at-rest to protect)
- Onboarding time goes from ~30 min (sign up 3 services) to ~5 min (clone +
  paste keys into `.env`)
- Ray pays for his own API usage — knows exact costs, no subsidy needed

**Negative:**
- Can't invite a friend to "just try it" without them creating 3 accounts
- Zero monetization path without rebuilding auth (see `docs/migration/v1-path.md`)

**Ruled out for now:**
- Public signup, payments integration, usage quotas
