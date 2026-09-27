#!/usr/bin/env bash
# Protects the Terraria server from connection spam and blocks IPs.
# Docker bypasses ufw for published ports, so the rules go in Docker's
# DOCKER-USER chain. Blocks are remembered in blocked-ips.txt and everything
# is re-applied after a reboot.
#
# Anti-spam (always on): each IP may open at most 20 new connections per
# minute to the game port. A real player uses one; scanner bots use hundreds.
#
#   sudo ./scripts/block-ip.sh 1.2.3.4           block an IP
#   sudo ./scripts/block-ip.sh 1.2.3.0/24        block a range
#   sudo ./scripts/block-ip.sh --remove 1.2.3.4  unblock
#   sudo ./scripts/block-ip.sh --list            show blocked IPs
#   sudo ./scripts/block-ip.sh --apply           turn on anti-spam + re-apply blocks
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LIST="blocked-ips.txt"
touch "$LIST"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/block-ip.sh <ip>" >&2
  exit 1
fi

rule() { iptables "$1" DOCKER-USER -s "$2" -j DROP; }

# Container-side port: DOCKER-USER sees packets after Docker's port mapping.
ratelimit() {
  iptables "$1" DOCKER-USER -p tcp --dport 7777 -m conntrack --ctstate NEW \
    -m hashlimit --hashlimit-name terraria --hashlimit-mode srcip \
    --hashlimit-above 20/minute --hashlimit-burst 20 -j DROP
}

apply_all() {
  iptables -N DOCKER-USER 2>/dev/null || true
  ratelimit -C 2>/dev/null || ratelimit -I
  local ip
  while read -r ip; do
    [[ -z "$ip" ]] && continue
    rule -C "$ip" 2>/dev/null || rule -I "$ip"
  done < "$LIST"
}

# Re-apply on every boot, after Docker has started.
cat > /etc/cron.d/terraria-blocklist <<CRON
@reboot root sleep 30 && ${ROOT}/scripts/block-ip.sh --apply
CRON

case "${1:-}" in
  "" ) echo "Usage: $0 <ip> | --remove <ip> | --list | --apply" >&2; exit 1 ;;
  --list )  cat "$LIST" ;;
  --apply ) apply_all; echo "Anti-spam protection is on." ;;
  --remove )
    ip="${2:?Usage: $0 --remove <ip>}"
    grep -vxF "$ip" "$LIST" > "$LIST.tmp" || true; mv "$LIST.tmp" "$LIST"
    while rule -C "$ip" 2>/dev/null; do rule -D "$ip"; done
    echo "Unblocked $ip" ;;
  * )
    ip="$1"
    grep -qxF "$ip" "$LIST" || echo "$ip" >> "$LIST"
    apply_all
    echo "Blocked $ip" ;;
esac
