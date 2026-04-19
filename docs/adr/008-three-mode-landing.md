# ADR 008 — Three-mode landing page

**Status:** Accepted
**Date:** 2026-04-18
**Supersedes:** v0.4's single-chat-input landing (ADR 007)

## Context

ADR 007 introduced the conversational coach as the single web UX. In practice:
- **Returning users** find the coach slow for simple questions ("what's AAPL's
  MOS right now?")
- **Portfolio-holders** want to open the app and see their holdings state,
  not start a new audit every time
- **New users** still benefit from the guided coach

One mode doesn't fit three use cases.

## Decision

Landing page `/` presents **three side-by-side mode cards**, each with its
own input/CTA visible on the card:

1. **🔍 快问快答** (`/ask`) — Perplexity-style: single question, structured
   answer with master-quote citations. Best for returning users who know what
   they want. Runs only relevant stages (not always 8).
2. **🎯 教练模式** (`/chat`) — existing v0.4 coach flow. Best for deep
   learning-oriented review.
3. **📊 投资秘书** (`/portfolio`) — portfolio-first dashboard with today's
   briefing (stale theses, holdings in buy/sell zones, upcoming earnings).
   Best for daily check-ins.

Each card renders its own input on the landing (no secondary click before the
user can act). User clicks one and immediately proceeds.

## Why

- **Visible choice** beats "hidden modes behind a dropdown" — per Ray's
  explicit UX feedback: "一眼看上去很直观"
- Each mode has a distinct **pace + user intent**, so co-existing helps
  rather than confuses
- **No mode is dominant**: the card UI makes "secretary mode" equally
  discoverable as "chat mode", which matters because secretary is the
  long-term-retention killer feature (daily habit)

## Consequences

**Positive:**
- Higher activation for all three user types
- Secretary mode gets visibility from day one
- Existing `/chat` and `/portfolio` routes unchanged; only `/ask` is new

**Negative:**
- Three parallel code paths to maintain
- Ask mode needs an intent-routing Haiku call (+$0.01/ask)
- Mobile layout needs careful stacking (3 cards stack vertically)

**Ruled out:**
- Dropdown mode selector (worse discoverability)
- Tab-style switcher (only shows one mode content at a time)
- Wizard with "choose your adventure" button (extra click before work)
