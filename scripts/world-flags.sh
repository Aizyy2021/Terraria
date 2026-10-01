#!/usr/bin/env bash
# Shows or changes NPC/boss progression flags in the server's world file.
#
#   sudo ./scripts/world-flags.sh                     show the flags (server keeps running)
#   sudo ./scripts/world-flags.sh --unsave mechanic   mark the Mechanic as not freed
#
# Changing a flag stops the server (the world is saved first), makes a
# backup, edits the one flag, and starts the server again (~30 seconds).
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/world-flags.sh" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  exec python3 scripts/world_flags.py
fi

echo "==> Stopping the server (the world is saved first)"
docker compose stop terraria
trap 'echo; echo "==> Starting the server"; docker compose up -d terraria' EXIT

echo "==> Backing up"
./scripts/backup.sh

echo "==> Editing the world"
python3 scripts/world_flags.py "$@"
