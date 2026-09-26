#!/usr/bin/env bash
# Blocks IP addresses (or ranges) from reaching the Terraria server.
# Docker bypasses ufw for published ports, so the rules go in Docker's
# DOCKER-USER chain. Blocks are remembered in blocked-ips.txt and re-applied
# after a reboot.
#
#   sudo ./scripts/block-ip.sh 1.2.3.4           block an IP
#   sudo ./scripts/block-ip.sh 1.2.3.0/24        block a range
#   sudo ./scripts/block-ip.sh --remove 1.2.3.4  unblock
#   sudo ./scripts/block-ip.sh --list            show blocked IPs
#   sudo ./scripts/block-ip.sh --apply           re-apply all (used at boot)
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

apply_all() {
  iptables -N DOCKER-USER 2>/dev/null || true
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
  --apply ) apply_all ;;
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
