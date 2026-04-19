# ADR 007 — Conversational-coach UX over form-based

**Status:** Accepted
**Date:** 2026-04-18
**Supersedes:** v0.3's `/audit/new` form flow

## Context

v0.3 had a 4-field form (ticker / anchor_thesis / market_expectation /
variant_view) plus a tech-mode checkbox. After submit, the user waited 3-5
minutes staring at a button labeled "审视中..." with no progress indication.

Review from PM + frontend perspectives surfaced 4 new-user friction points:
1. "variant view" is jargon; new users don't know what to write
2. No guidance on *which* ticker to audit
3. Static 5-minute wait with no feedback
4. Dense 8-stage report dump when it finally arrives

## Decision

Redesign `/` as a **conversational interface**:
- Single chat input ("你想审视哪只股票？")
- Coach (implemented via `engine/coach.py` + Haiku) asks follow-up
  questions to elicit anchor thesis in plain language
- SSE-streamed stage-by-stage commentary as the audit runs
- Master quotes interleaved at stage transitions (topic-matched)
- Final card with Munger-style self-questions, not a cold BUY/SELL label

Keep `/audit/new` as a **legacy backup** for bookmark URLs and CLI users.

## Why

- Conversation → **elicitation** of hidden priors (user's mental model of the
  company) without making them type in jargon boxes
- Streaming → **progress feedback** cures the silent 5-minute wait
- Quotes at transitions → **internalizes** the "slow down" philosophy without
  a disclaimer box
- No cold verdict label → **resists** the "AI told me to buy" trap

## Consequences

**Positive:**
- New-user onboarding drops from ~5 min reading to ~30 sec typing
- The philosophy ("activity is the enemy") is in the experience, not just
  in copy
- SSE + coach commentary adds ~$0.04/audit (Haiku cost) for a much better UX

**Negative:**
- More moving parts: SSE stream, session state, coach fallback path
- Harder to test end-to-end (requires mocked provider responses)
- Can't bookmark "the audit in progress"

**Ruled out:**
- Multi-turn open-ended chat (the conversation is scripted — 1 elicitation
  then 8 staged reports then Munger questions; unlike ChatGPT, not a free
  back-and-forth)
- Voice input / audio output (overengineered)
