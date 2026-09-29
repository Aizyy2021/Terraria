#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu VPS. Safe to re-run: it also applies
# changes you make to .env (password, player count, …).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/setup.sh" >&2
  exit 1
fi

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Installing Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
else
  echo "Docker already installed."
fi

step "Creating .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
set -a; source .env; set +a
if [[ -z "${SERVER_PASSWORD:-}" ]]; then
  while true; do
    read -rsp "Choose a server password for your friends: " pw1; echo
    read -rsp "Repeat it: " pw2; echo
    if [[ -z "$pw1" || "$pw1" != "$pw2" ]]; then
      echo "Passwords were empty or didn't match — try again."
    elif [[ "$pw1" == *"'"* ]]; then
      echo "Please don't use a single quote (') in the password — try again."
    else
      break
    fi
  done
  # Single quotes keep $, spaces etc. literal for both bash and Docker Compose.
  python3 - "$pw1" <<'PY'
import sys, re, pathlib
p = pathlib.Path(".env")
p.write_text(re.sub(r"(?m)^SERVER_PASSWORD=.*$", lambda _: f"SERVER_PASSWORD='{sys.argv[1]}'", p.read_text()))
PY
  chmod 600 .env
  set -a; source .env; set +a
fi

step "Preparing folders and TShock config"
mkdir -p data/tshock data/worlds data/plugins backups
# TShock fills in every setting we don't specify, so we only set the ones we care about.
python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path("data/tshock/config.json")
cfg = json.loads(path.read_text()) if path.exists() else {}
s = cfg.setdefault("Settings", {})
s.update({
    "ServerPassword": os.environ["SERVER_PASSWORD"],
    "MaxSlots": int(os.environ["MAX_PLAYERS"]),
    "AutoSave": True,
    "BackupInterval": 30,       # TShock snapshot every 30 min…
    "BackupKeepFor": 720,       # …kept for 12 hours
    "SaveWorldOnCrash": True,
    "RestApiEnabled": False,
})
path.write_text(json.dumps(cfg, indent=2))
PY
chmod 600 data/tshock/config.json

step "Configuring firewall"
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null
  ufw allow "${SERVER_PORT}/tcp" >/dev/null
  ufw --force enable >/dev/null
  echo "Open ports: SSH and ${SERVER_PORT}/tcp."
else
  echo "ufw not found — make sure TCP port ${SERVER_PORT} is open in your provider's firewall."
fi

step "Turning on anti-spam protection"
chmod +x scripts/*.sh
./scripts/block-ip.sh --apply

step "Scheduling nightly backups (05:00)"
cat > /etc/cron.d/terraria-backup <<CRON
0 5 * * * root ${ROOT}/scripts/backup.sh >> ${ROOT}/backups/backup.log 2>&1
CRON
chmod +x scripts/*.sh

step "Installing the freeze watchdog"
./scripts/watchdog.sh

step "Starting the server"
docker compose pull
docker compose up -d
echo "Generating the world on first start can take a minute or two…"

for _ in $(seq 1 90); do
  [[ -f data/tshock/setup-code.txt ]] && break
  if docker compose logs terraria 2>/dev/null | grep -q "Server started"; then break; fi
  sleep 2
done

IP="$(curl -fsS4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo
echo "────────────────────────────────────────────"
echo "  Server is up."
echo "  Friends join with:  ${IP}:${SERVER_PORT}"
if [[ -f data/tshock/setup-code.txt ]]; then
  echo "  Admin setup code:   $(cat data/tshock/setup-code.txt)"
  echo "  (In-game, type /setup <code> — see README → Become admin)"
fi
echo "────────────────────────────────────────────"
