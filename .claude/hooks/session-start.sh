#!/bin/bash
# Project-level SessionStart hook for moatlens (2026-06-06).
#
# WHY in the repo: a project .claude/ hook travels to EVERY machine via git, so
# the NAS (and any future machine) automatically gets the same session bootstrap
# the moment it clones — no per-machine hook setup. Claude Code runs project-level
# SessionStart hooks and they OVERRIDE the global ~/.claude hook when cwd is in
# this project, so this script is self-contained.
#
# Does (stdout becomes the injected session context):
#   1. inject _WORK.md head (machine-LOCAL detailed state, gitignored)
#   2. inject BOTH machines' _HANDOFF_*.md (tracked cross-machine 接力)
#
# This hook does NOT run the app, tests, or any pipeline — context injection only.
set -u

# Project root: prefer Claude Code's env var; else derive from this script's path
# (.claude/hooks/session-start.sh → ../.. = repo root). Robust across machines.
PROJ="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# 1. Local working state (gitignored, per-machine).
if [ -f "$PROJ/_WORK.md" ]; then
  echo "--- _WORK.md head (auto-injected, machine-local) ---"
  head -60 "$PROJ/_WORK.md"
  echo "--- end _WORK.md head ---"
fi

# 2. Cross-machine handoff — inject BOTH (tracked, travels via git), so a session
#    on either machine sees what the other did.
for hf in _HANDOFF_mac.md _HANDOFF_nas.md; do
  if [ -f "$PROJ/$hf" ]; then
    echo ""
    echo "--- $hf (cross-machine 接力) ---"
    head -45 "$PROJ/$hf"
    echo "--- end $hf ---"
  fi
done

exit 0
