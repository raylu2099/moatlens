# ADR 002 — Filesystem storage over SQLite

**Status:** Accepted
**Date:** 2026-04-18

## Context

v0.1 used SQLite for: user accounts, per-user audit index, shared-report slugs.
When we collapsed to single-user (ADR 001), we removed users + shared_reports
tables but kept the audit_index for fast listing.

Question: keep SQLite for the audit index, or drop to pure filesystem?

## Decision

Pure filesystem. Audits live at `data/audits/<TICKER>/<YYYY-MM-DD>.{md,json}`.
List operation walks the directory; cost is cached in an incremental index
file `data/audits/_index.json` (rebuilt on-save, auto-repair on staleness).

## Why

- **No concurrent writers**: single user, single process. SQLite's main value
  (WAL + locking) is irrelevant.
- **Audit snapshots are already human-readable JSON**: version-controllable,
  diffable with `git diff`, inspectable with `jq`.
- **Zero migration risk**: no schema changes to worry about across versions.
- **Simpler backup**: `rsync data/` is enough. SQLite would need `.backup`
  or vacuum.
- **Filesystem is atomic enough** for our needs (tempfile + `os.replace`).

## Consequences

**Positive:**
- No db migrations
- Backup = rsync
- Can edit an audit JSON manually and have it reflected immediately

**Negative:**
- `list_audits` is O(N) when index missing; mitigated by the index cache
- No full-text search across audits (but `grep` + `rg` work)
- No transactions across multiple writes (chat session + audit save + index);
  mitigated by atomic individual writes

**Ruled out:**
- Complex queries ("show me all audits where Stage 5 OE margin < 10% in 2025")
  would require either rebuilding a DB or pulling all JSONs. Acceptable
  trade-off at personal scale.

## Re-evaluation trigger

If audit count exceeds ~500, or if Ray wants sophisticated filtering/search,
reconsider SQLite as a _read-only query layer_ that mirrors filesystem truth.
