#!/bin/bash
# Moatlens nightly ops — orchestrates the things that would otherwise
# grow into disk / data problems. Add to crontab for NAS deployment:
#
#   15 3 * * * /volume1/homes/hellolufeng/Drive/moatlens/bin/nightly.sh >> /var/log/moatlens-nightly.log 2>&1
#
# (Scheduled 15 minutes after backup.sh at 03:00, so backup sees the
# pre-cleanup state.)
#
# Environment:
#   MOATLENS_DATA_DIR      (inherited; defaults to repo-local data/)
#   MOATLENS_CACHE_MAX_AGE_DAYS   (default 30)
#   MOATLENS_COST_KEEP_DAYS       (default 90)
#   MOATLENS_NIGHTLY_PYTHON       (path to python; auto-detects NAS vs Mac)
#
# What it does:
#   1. doctor.py health check  (9 providers → log)
#   2. Cache cleanup           (delete cache entries older than N days)
#   3. Cost log rollup         (archive entries > N days to monthly files)
#   4. Chat/Ask session TTL    (normally runs on uvicorn startup; cron ensures
#                               idle machines still prune)
#   5. Stale-audit quick count (just log, no action — sentinel metric)
#
# Exits non-zero on doctor-level failure so cron's mailer can notify;
# cleanup failures are logged but don't fail the script (best-effort).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${PROJECT_DIR}"

# --- Python resolution: prefer NAS micromamba, else Mac venv --------------
if [ -z "${MOATLENS_NIGHTLY_PYTHON:-}" ]; then
    if [ -x "/volume1/homes/hellolufeng/bin/micromamba" ]; then
        export MAMBA_ROOT_PREFIX=/volume1/homes/hellolufeng/micromamba
        MOATLENS_NIGHTLY_PYTHON="/volume1/homes/hellolufeng/bin/micromamba run -n ytdlp python"
    elif [ -x "${HOME}/.venvs/moatlens/bin/python" ]; then
        MOATLENS_NIGHTLY_PYTHON="${HOME}/.venvs/moatlens/bin/python"
    else
        echo "[$(date -Iseconds)] ERROR: no python env found" >&2
        exit 2
    fi
fi

CACHE_MAX_AGE_DAYS="${MOATLENS_CACHE_MAX_AGE_DAYS:-30}"
COST_KEEP_DAYS="${MOATLENS_COST_KEEP_DAYS:-90}"

echo "[$(date -Iseconds)] moatlens-nightly START"
echo "[$(date -Iseconds)] python: ${MOATLENS_NIGHTLY_PYTHON}"

# --- 1. doctor.py (capture exit code for final status) -------------------
DOCTOR_RC=0
if [ -x bin/doctor.py ]; then
    echo "[$(date -Iseconds)] --- doctor ---"
    ${MOATLENS_NIGHTLY_PYTHON} bin/doctor.py || DOCTOR_RC=$?
fi

# --- 2. Cache cleanup ----------------------------------------------------
echo "[$(date -Iseconds)] --- cache_clear_stale (max age ${CACHE_MAX_AGE_DAYS}d) ---"
${MOATLENS_NIGHTLY_PYTHON} -c "
import sys
sys.path.insert(0, '.')
from shared.config import load_config
from engine.cache import cache_clear_stale
cfg = load_config()
n = cache_clear_stale(cfg, max_age_seconds=${CACHE_MAX_AGE_DAYS}*86400)
print(f'deleted {n} cache entries')
" || echo "[$(date -Iseconds)] WARN: cache cleanup failed (continuing)"

# --- 3. Cost log rollup --------------------------------------------------
echo "[$(date -Iseconds)] --- archive_cost_log (keep ${COST_KEEP_DAYS}d live) ---"
${MOATLENS_NIGHTLY_PYTHON} -c "
import sys
sys.path.insert(0, '.')
from shared.config import load_config
from shared.metrics import archive_cost_log
cfg = load_config()
archived, kept = archive_cost_log(cfg, keep_days=${COST_KEEP_DAYS})
print(f'archived {archived} entries, kept {kept} in live log')
" || echo "[$(date -Iseconds)] WARN: cost archive failed (continuing)"

# --- 4. Chat/Ask session cleanup -----------------------------------------
echo "[$(date -Iseconds)] --- session TTL cleanup ---"
${MOATLENS_NIGHTLY_PYTHON} -c "
import sys
sys.path.insert(0, '.')
from shared.config import load_config
from shared.chat import cleanup_expired as cleanup_chats
from shared.ask import cleanup_expired as cleanup_asks
cfg = load_config()
print(f'chat cleanup: {cleanup_chats(cfg)} removed')
print(f'ask cleanup:  {cleanup_asks(cfg)} removed')
" || echo "[$(date -Iseconds)] WARN: session cleanup failed (continuing)"

# --- 5. Stale-audit count (sentinel log line only) -----------------------
echo "[$(date -Iseconds)] --- stale audit count ---"
${MOATLENS_NIGHTLY_PYTHON} -c "
import sys
sys.path.insert(0, '.')
from shared.config import load_config
from shared.storage import list_audits
cfg = load_config()
rows = list_audits(cfg)
stale = sum(1 for r in rows if r.get('stale_level') in ('stale','very_stale'))
print(f'{len(rows)} audits total, {stale} stale (≥90 days)')
" || echo "[$(date -Iseconds)] WARN: audit count failed (continuing)"

echo "[$(date -Iseconds)] moatlens-nightly END (doctor_rc=${DOCTOR_RC})"
exit ${DOCTOR_RC}
