# ADR 001 — Single-user mode over multi-tenant SaaS

**Status:** Accepted
**Date:** 2026-04-18
**Snapshot tag:** `v0.1-multi-tenant-snapshot`

## Context

v0.1 was built as a multi-tenant BYOK SaaS: login, per-user API-key encryption,
public share pages, SEO. The assumption was Ray would productize Moatlens.

After a three-perspective code review (Anthropic engineer / professional dev / PM),
the conclusion was:
1. BYOK flow loses ~90% of potential users before they run their first audit
2. Ray himself is the target user; the product philosophy ("slow down the
   thinker") is anti-engagement, hard to monetize
3. 800 lines of auth/encryption/multi-tenant code were a net drag on iteration
   speed for a v0.1 with zero other users

## Decision

Collapse to single-user mode. Web server binds to `127.0.0.1`. Keys read from
`.env`. Delete `web/auth.py`, `web/keys_manager.py`, `shared/crypto.py`,
`shared/db.py`, related templates.

Preserve the SaaS scaffold at tag `v0.1-multi-tenant-snapshot` — recoverable if
Ray decides to productize in three months.

## Consequences

**Positive:**
- Iteration speed +3x (no auth boilerplate to navigate)
- 100% less attack surface (no CSRF/XSS/KDF concerns for a local tool)
- Full `.env` control (no per-user DB schema to maintain)

**Negative:**
- If Ray productizes later, ~800 lines need to be restored (from the tag)
- No shareable reports for now (Ray can manually share the markdown files)

**Ruled out:**
- Any feature requiring user-isolation (until v1.x migration)
- Browser-based "demo for friends" use case (they must clone the repo)

## Re-evaluation trigger

At 2026-07-18, if Ray says "yes I really want this public", restore from tag
and follow `docs/migration/v1-path.md`.
