#!/bin/bash
# Moatlens backup — rsync data/ to a sibling backup dir with date stamp.
#
# Add to crontab for nightly backup:
#   0 3 * * * /volume1/homes/hellolufeng/Drive/moatlens/bin/backup.sh >> /var/log/moatlens-backup.log 2>&1
#
# For cross-machine backup (to US NAS via tailscale), change DST to
# rsync target spec like `user@100.114.1.70:/volume1/backups/moatlens/`.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${PROJECT_DIR}/data"
DST="${MOATLENS_BACKUP_DIR:-/volume1/homes/hellolufeng/backups/moatlens}"
KEEP_DAYS="${MOATLENS_BACKUP_KEEP_DAYS:-14}"

DATE_STAMP="$(date +%Y-%m-%d)"
SNAPSHOT_DIR="${DST}/${DATE_STAMP}"

mkdir -p "${SNAPSHOT_DIR}"

echo "[$(date -Iseconds)] backing up ${SRC} → ${SNAPSHOT_DIR}"

# --link-dest makes unchanged files hardlink to yesterday's snapshot → efficient
YESTERDAY="$(date -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -v -1d +%Y-%m-%d 2>/dev/null || echo "")"
LINK_DEST_ARG=""
if [ -n "${YESTERDAY}" ] && [ -d "${DST}/${YESTERDAY}" ]; then
    LINK_DEST_ARG="--link-dest=${DST}/${YESTERDAY}"
fi

rsync -a --delete ${LINK_DEST_ARG} \
    --exclude='cache/' \
    "${SRC}/" "${SNAPSHOT_DIR}/"

# Prune old snapshots
find "${DST}" -maxdepth 1 -type d -name '????-??-??' \
    -mtime +"${KEEP_DAYS}" -exec rm -rf {} +

echo "[$(date -Iseconds)] done. kept: $(ls "${DST}" | wc -l) snapshots"
