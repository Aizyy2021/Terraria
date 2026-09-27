#!/usr/bin/env bash
# Sets up (or turns off) Discord join/leave notifications.
#
#   sudo ./scripts/discord.sh          paste a webhook URL and turn it on
#   sudo ./scripts/discord.sh --off    turn notifications off
#
# Get a webhook URL in Discord: channel ⚙ Edit Channel → Integrations →
# Webhooks → New Webhook → Copy Webhook URL.
set -euo pipefail

cd "$(dirname "$0")/.."

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

if [[ "${1:-}" == "--off" ]]; then
  docker compose --profile discord stop discord 2>/dev/null || true
  docker compose --profile discord rm -f discord 2>/dev/null || true
  set_env COMPOSE_PROFILES ""
  echo "Discord notifications turned off."
  exit 0
fi

read -rp "Paste your Discord webhook URL: " url
if [[ ! "$url" =~ ^https://(canary\.|ptb\.)?discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$ ]]; then
  echo "That doesn't look like a Discord webhook URL (https://discord.com/api/webhooks/…)." >&2
  exit 1
fi

echo "Sending a test message…"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"content":"✅ Terraria server notifications are set up.","allowed_mentions":{"parse":[]}}' "$url")
if [[ "$code" != "204" && "$code" != "200" ]]; then
  echo "Discord rejected the webhook (HTTP $code). Check the URL and try again." >&2
  exit 1
fi

set_env DISCORD_WEBHOOK_URL "$url"
set_env COMPOSE_PROFILES discord
chmod 600 .env

docker compose up -d discord
echo "Done — check your Discord channel for the test message."
