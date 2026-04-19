# Architecture Decision Records — Moatlens

This directory captures the **why** behind the biggest design decisions. Each ADR is
a short markdown file explaining: what was decided, when, why, and what it rules out.

**When to add an ADR:** any decision that would take ≥ 30 min to re-derive from
code six months from now. Examples: "why no SQLite", "why BYOK was dropped",
"why SSE instead of WebSocket".

**Format:** Michael Nygard's lightweight ADR template.

| # | Title | Status | Date |
|---|---|---|---|
| 001 | Single-user mode vs multi-tenant SaaS | Accepted | 2026-04-18 |
| 002 | Filesystem storage over SQLite | Accepted | 2026-04-18 |
| 003 | Drop BYOK, use .env directly | Accepted | 2026-04-18 |
| 004 | Chinese UI chrome with English technical terms | Accepted | 2026-04-18 |
| 005 | Externalized prompts + wisdom YAML | Accepted | 2026-04-18 |
| 006 | SSE over WebSocket for streaming | Accepted | 2026-04-18 |
| 007 | Conversational-coach UX over form-based | Accepted | 2026-04-18 |
| 008 | Three-mode landing page | Accepted | 2026-04-18 |

## Superseded / historical
(none yet)
