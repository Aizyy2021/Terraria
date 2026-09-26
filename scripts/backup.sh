#!/usr/bin/env bash
# Archives the world, config and TShock database into backups/.
# Runs nightly via cron; you can also run it by hand at any time.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

stamp="$(date +%Y-%m-%d_%H%M)"
tar -czf "backups/terraria_${stamp}.tar.gz" --exclude='data/tshock/logs' data
find backups -name 'terraria_*.tar.gz' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete

echo "$(date '+%F %T') saved backups/terraria_${stamp}.tar.gz"
