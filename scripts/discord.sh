#!/usr/bin/env bash
# Sets up (or turns off) the live Discord status message.
#
#   sudo ./scripts/discord.sh          paste a webhook URL and turn it on
#   sudo ./scripts/discord.sh --off    turn it off
#
# Get a webhook URL in Discord: channel ⚙ Edit Channel → Integrations →
# Webhooks → New Webhook → Copy Webhook URL.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
UNIT=/etc/systemd/system/terraria-discord.service

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/discord.sh" >&2
  exit 1
fi

# Sets KEY=value in .env, adding the line if it's missing.
set_env() {
  python3 - "$1" "$2" <<'PY'
import sys, re, pathlib
key, value = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
text = p.read_text()
line = f"{key}={value}"
if re.search(rf"(?m)^{key}=", text):
    text = re.sub(rf"(?m)^{key}=.*$", lambda _: line, text)
else:
    text = text.rstrip("\n") + "\n" + line + "\n"
p.write_text(text)
PY
}

# Remove the older one-message-per-event version if it's still around.
docker rm -f terraria-discord >/dev/null 2>&1 || true
set_env COMPOSE_PROFILES ""

if [[ "${1:-}" == "--off" ]]; then
  systemctl disable --now terraria-discord 2>/dev/null || true
  rm -f "$UNIT"
  systemctl daemon-reload
  echo "Discord status message turned off. (You can delete the message in Discord.)"
  exit 0
fi

current="$(grep -E '^DISCORD_WEBHOOK_URL=' .env | cut -d= -f2- || true)"
if [[ -n "$current" ]]; then
  read -rp "Keep the current webhook? [Y/n] " keep
  [[ "$keep" =~ ^[Nn]$ ]] && current=""
fi
url="$current"
if [[ -z "$url" ]]; then
  read -rp "Paste your Discord webhook URL: " url
fi
if [[ ! "$url" =~ ^https://(canary\.|ptb\.)?discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$ ]]; then
  echo "That doesn't look like a Discord webhook URL (https://discord.com/api/webhooks/…)." >&2
  exit 1
fi
code=$(curl -s -o /dev/null -w '%{http_code}' "$url")
if [[ "$code" != "200" ]]; then
  echo "Discord rejected the webhook (HTTP $code). Check the URL and try again." >&2
  exit 1
fi
set_env DISCORD_WEBHOOK_URL "$url"

if ! grep -qE '^SERVER_ADDRESS=.+' .env; then
  ip="$(curl -fsS4 https://ifconfig.me 2>/dev/null || true)"
  [[ -n "$ip" ]] && set_env SERVER_ADDRESS "$ip"
fi
grep -qE '^DISCORD_TITLE=' .env || set_env DISCORD_TITLE "Terraria Server"
chmod 600 .env

# Start fresh: a new webhook means a new message.
[[ "$url" != "$current" ]] && rm -f data/discord-status.json

cat > "$UNIT" <<UNITFILE
[Unit]
Description=Terraria Discord status message
After=docker.service
Wants=docker.service

[Service]
ExecStart=/usr/bin/python3 -u ${ROOT}/scripts/discord_status.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNITFILE

systemctl daemon-reload
systemctl enable terraria-discord >/dev/null
systemctl restart terraria-discord
sleep 5
if systemctl is-active --quiet terraria-discord; then
  echo "Done — the status message is now in your Discord channel and updates itself."
else
  echo "Something went wrong. Details:" >&2
  journalctl -u terraria-discord -n 20 --no-pager >&2
  exit 1
fi
