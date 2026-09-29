#!/usr/bin/env bash
# Installs the watchdog that restarts the Terraria server when it freezes.
#
#   sudo ./scripts/watchdog.sh           install / update
#   sudo ./scripts/watchdog.sh --status  what it's been doing
#   sudo ./scripts/watchdog.sh --off     remove it
#
# Diagnostics from every automatic restart are saved in data/incidents/.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
UNIT=/etc/systemd/system/terraria-watchdog.service

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/watchdog.sh" >&2
  exit 1
fi

case "${1:-}" in
  --status)
    systemctl --no-pager status terraria-watchdog | head -5
    echo; journalctl -u terraria-watchdog -n 20 --no-pager
    echo; ls -1 data/incidents 2>/dev/null | tail -5 || true
    exit 0 ;;
  --off)
    systemctl disable --now terraria-watchdog 2>/dev/null || true
    rm -f "$UNIT"; systemctl daemon-reload
    echo "Watchdog removed."
    exit 0 ;;
esac

cat > "$UNIT" <<UNITFILE
[Unit]
Description=Restarts the Terraria server when it freezes
After=docker.service
Wants=docker.service

[Service]
ExecStart=/usr/bin/python3 -u ${ROOT}/scripts/watchdog.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNITFILE

systemctl daemon-reload
systemctl enable terraria-watchdog >/dev/null
systemctl restart terraria-watchdog
sleep 2
systemctl is-active --quiet terraria-watchdog \
  && echo "Watchdog is running. A frozen server is now restarted automatically within ~3 minutes." \
  || { journalctl -u terraria-watchdog -n 20 --no-pager >&2; exit 1; }
