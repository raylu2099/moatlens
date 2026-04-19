# ADR 005 — Externalized prompts + wisdom YAML

**Status:** Accepted
**Date:** 2026-04-18

## Context

v0.1 had all Claude system prompts hardcoded inside stage Python files. To
tune Stage 3's moat-analysis prompt, you'd edit `engine/stages/s3_moat.py`,
run tests (to confirm nothing broke structurally), and have no history of
which prompt version produced which audit.

## Decision

**Prompts** live at `prompts/s{3,4,8}_*.md` — one file per stage. First line
may contain `<!-- version: N -->`. Loaded via `engine/prompts_loader.py`
(mtime-aware cache so edits picked up without restart).

**Master quotes** live at `prompts/wisdom.yaml` with schema:
```yaml
- id: <stable_slug>
  author: <string>
  text_en: <string>
  text_cn: <string>
  source: <string>
  themes: [tag...]
  stages: [int...]
  triggers: [tag...]
  ray_note: <optional string>
```

Each audit records `prompt_slug` and `prompt_version` in its raw_data so we
can replay / compare.

## Why

- **Prompts are data, not code**: iterating on prompt text shouldn't require a
  code review or test run
- **Version pinning is critical for comparison**: "this audit used prompt
  v2, that one used v3 — did the change improve?"
- **Non-coder edit path**: future collaborator (or future Ray's assistant)
  can edit markdown directly
- **Wisdom YAML serves two purposes**: (1) content for `/wisdom` library
  page, (2) runtime injection into coach commentary at matching stages/triggers

## Consequences

**Positive:**
- Prompt changes don't count as code diffs (cleaner git history)
- A/B comparison becomes possible (see future ADR once implemented)
- YAML is diffable, reviewable, easy to validate in CI

**Negative:**
- Prompt files can desync from stage code (e.g., prompt asks for field X,
  code doesn't parse it) — mitigated by tests that mock Claude with sample
  output
- YAML is more error-prone than Python (indentation + quoting) — mitigated
  by a CI test that parses and sanity-checks wisdom.yaml

## Related

- `engine/prompts_loader.py`, `engine/wisdom.py`
- `tests/test_prompts_loader.py`, `tests/test_wisdom.py`
