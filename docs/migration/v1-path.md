# v1.0 Migration Path — Self-use → Public SaaS

**Trigger:** if at 2026-07-18 Ray answers yes to the three self-evaluation
questions in `project_moatlens.md`, this doc is the roadmap from the
single-user tool back toward productization.

This is a _plan_, not a commitment. If the product thesis has shifted, rewrite
this doc.

---

## Phase 0 — Decision gate (day 0)

Before writing any code, write a 1-page strategy memo:
- Who is the target paying user? (not "value investors" — too broad)
- What is the pricing model? (subscription / per-report / freemium / BYOK)
- What is the unique wedge vs Seeking Alpha, Koyfin, Simply Wall St?
- What does "v1 shipped" mean, operationally? (signups? MRR? DAU?)

If the memo can't be written clearly, don't migrate yet.

---

## Phase 1 — Restore multi-tenant scaffold (week 1)

Base branch: `v0.1-multi-tenant-snapshot` (tagged at commit `416fb5b`).

Cherry-pick into a new `v1-dev` branch:
- `web/auth.py` — **must be rewritten** with PBKDF2 or Argon2 (see #fix1)
- `web/keys_manager.py` — revisit BYOK decision (ADR 003) before bringing back
- `shared/crypto.py` — **rewrite** with:
  - PBKDF2-HMAC-SHA256 (iterations ≥ 600k as of 2026) OR Argon2id
  - Per-user 16-byte random salt stored alongside ciphertext
  - Envelope encryption: server KEK + per-user DEK
- `shared/db.py` — keep users + api_keys tables; **drop** `shared_reports`
  (replace with proper sharing model)
- Auth templates (login, signup) — keep, restyle to match current design

### #fix1 — Security backlog before re-enabling auth

**Non-negotiable:**
- [ ] CSRF middleware (starlette-csrf or custom double-submit cookie)
- [ ] Cookie `secure=True`, `httponly`, `samesite=lax`
- [ ] Rate limit on `/login`, `/signup` (slowapi: 5/min per IP)
- [ ] Password reset flow via signed email tokens (itsdangerous)
- [ ] Account lockout after 10 failed logins
- [ ] 2FA option (TOTP via pyotp)
- [ ] Logout clears session server-side, not just cookie
- [ ] Audit log for auth events (login/logout/pw change/key rotation)

**Should-have:**
- [ ] Email verification before first audit
- [ ] User-visible session list (revoke any)
- [ ] Export all user data ("download everything") for GDPR

---

## Phase 2 — Drop ADR 001's single-user assumption (week 2)

Mechanical changes to restore user isolation:
- `shared/storage.py` — reintroduce `user_id` parameter (already exists in
  git history); add back `data/audits/<user_id>/` namespacing
- `shared/holdings.py` — namespace holdings per-user similarly
- `shared/chat.py` — namespace chat sessions per-user
- `engine/orchestrator.py` — plumb `user_id` through where needed
- Web routes — decorate with `@require_user`; replace `cfg.data_dir` with
  user-scoped paths

---

## Phase 3 — BYOK vs hosted decision (week 3)

Option A — **Hosted**: server uses its Anthropic/Perplexity/FD keys. Passes
  cost to user via subscription ($X/mo) or pay-per-report ($Y).
  - **Pros**: zero onboarding friction, predictable UX
  - **Cons**: operator carries cost, need billing integration (Stripe)

Option B — **BYOK**: users enter their own keys (as v0.1 did).
  - **Pros**: zero API cost to operator, compliance-friendly
  - **Cons**: ~86% onboarding drop-off (ADR 003)

Option C — **Hybrid**: free tier = 3 audits/mo on operator's key; paid tier
  = BYOK unlimited.
  - **Pros**: try-before-commit + power-user path
  - **Cons**: double the complexity

Default recommendation: **A (hosted) with Stripe**, unless the target user
is enterprises with compliance requirements.

---

## Phase 4 — Product surface (week 4)

Reframe current v0.4 features for multi-user:
- Chat mode → user's private chat history per ticker
- Ask mode → "public Q&A feed" for discovery? (research: legal / IA risk)
- Portfolio → user's private holdings
- Wisdom → public library (seed from current wisdom.yaml, allow users to
  bookmark quotes to their own "Ray-note" equivalent)

Add:
- Sharing: user can make one audit public via slug (resurrect
  `shared_reports` table from tag but redesign schema)
- Follow: subscribe to another user's public audits (Twitter-like)

---

## Phase 5 — Compliance + risk (week 5)

Legal minimums in US:
- Footer disclaimer every page: "Not investment advice. Not an investment
  adviser. Moatlens is educational software."
- Terms of Service with arbitration + liability cap
- Privacy Policy (cookies, analytics, data retention)
- SEC Investment Advisers Act check: as long as we don't give specific buy/
  sell recommendations or take custody of funds, we're in "financial software"
  territory, not "investment advice". But "BUY / AVOID / WATCH" labels *per
  ticker* are a grey zone — consider softening to "qualifies / needs review /
  fails screen" language for public share pages.

Non-US: if expanding to CN or UK, separate consult.

---

## Phase 6 — Infra scale-out (week 6)

Move from `127.0.0.1` + Synology NAS to:
- Containerized (existing Dockerfile) + `docker compose` on a small VPS
- Postgres (not SQLite) for user data
- Redis for chat session state and rate limits
- S3-compatible for audit MD/JSON (keep current filesystem layout, just in
  cloud)
- Cloudflare in front for DDoS + TLS

Cost envelope estimate: ~$50/mo at zero users, ~$200-400/mo at 500 users.

---

## Phase 7 — Payments + onboarding (week 7-8)

If Option A or C from Phase 3:
- Stripe Checkout for subscription
- Webhook handling for subscription lifecycle
- Usage metering (audits/mo) per account
- Trial period logic

---

## What to delete from this doc once migrated

Each phase above gets checkboxes crossed off. When a phase is complete in
production, move its detail to a new ADR and trim this doc.
