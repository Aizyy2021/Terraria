#!/usr/bin/env bash
# Restores a backup made by backup.sh.
# Usage: sudo ./scripts/restore.sh backups/terraria_2026-01-01_0500.tar.gz
set -euo pipefail

cd "$(dirname "$0")/.."
archive="${1:?Usage: $0 backups/terraria_<date>.tar.gz}"
[[ -f "$archive" ]] || { echo "No such file: $archive" >&2; exit 1; }

read -rp "This replaces the current world with ${archive}. Continue? [y/N] " ok
[[ "$ok" =~ ^[Yy]$ ]] || exit 0

docker compose stop
mv data "data.before-restore.$(date +%s)"
tar -xzf "$archive"
docker compose up -d
echo "Restored. The previous data was kept in data.before-restore.*"
