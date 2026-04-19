# ADR 004 — Chinese UI chrome with English technical terms

**Status:** Accepted
**Date:** 2026-04-18

## Context

Moatlens' primary user is Ray (native Chinese speaker, bilingual). Early v0.1
shipped mixed UI: nav in English, metric names in Chinese, Claude prompts in
Chinese, findings in Chinese. This was incoherent — new contributors/users
had to code-switch per screen.

## Decision

Strict convention:
1. **UI chrome in Chinese**: nav, buttons, form labels, table headers, empty
   states, error messages, footer.
2. **Technical acronyms in English**: DCF, WACC, ROIC, FCF, PE, Monte Carlo,
   Sonnet, Haiku, SSE. These are international terminology where translating
   adds confusion, not clarity.
3. **Ticker symbols always English uppercase**: AAPL, NVDA, BRK.B.
4. **Master quotes bilingual**: Chinese translation (from official sources)
   alongside English original + source citation.
5. **Code comments, docstrings, commit messages**: English (for the GitHub
   community and future migration).

## Why

- Ray thinks in Chinese when investing, but finance uses English jargon globally
- `WACC` is clearer than `加权平均资本成本` — the latter is 8 characters for
  a concept every finance reader already knows by the acronym
- Bilingual quotes preserve original nuance (for quote-nerds) while staying
  accessible

## Consequences

**Positive:**
- Cleaner visual density (acronyms are compact)
- Easier to copy-paste tickers or metric names to Google/Bloomberg
- Master quotes have citational integrity

**Negative:**
- A monolingual Chinese reader may hit `WACC` once and need a glossary
  (mitigated: `/learn/` has concept explanations)
- A monolingual English reader has a harder time (but the target user isn't
  that)

## Glossary (quick reference)

Kept in English: DCF, WACC, ROIC, ROE, FCF, OCF, NI, SBC, PE, PS, EV/EBITDA,
PEG, Monte Carlo, Z-score, F-score, Kelly, Sonnet, Haiku, SSE, BYOK.

Translated in prose: 能力圈 (circle of competence), 护城河 (moat), 安全边际
(margin of safety), 非对称性 (asymmetry), 反过来想 (inversion).
