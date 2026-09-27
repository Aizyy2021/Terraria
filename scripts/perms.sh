#!/usr/bin/env bash
# Unlocks everything a normal Terraria player can do for all players.
#
# TShock is built for public servers, so by default it blocks lots of
# ordinary gameplay (wormhole potions, pylons, summoning bosses, fast
# mining…) for anyone who isn't an admin. This grants all of it to the
# `guest` group, which every other group inherits from.
#
# Still admin-only: spawning items (/item, /give), teleport commands
# (/tp, /home, /spawn, /warp), /godmode, /heal, /buff, /time, /worldevent,
# spawning bosses/mobs by command, and moderation.
#
# Restarts the server (~30 seconds). Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."

PERMS=(
  # building & world
  tshock.world.modify tshock.world.paint tshock.world.movenpc tshock.world.worldupgrades
  tshock.world.time.usesundial tshock.world.time.usemoondial tshock.world.toggleparty
  # bosses, events, NPCs
  tshock.npc.summonboss tshock.npc.startinvasion tshock.npc.startdd2 tshock.npc.spawnpets
  tshock.npc.hurttown tshock.npc.rename
  # teleport *items* (not commands)
  tshock.tp.wormhole tshock.tp.pylon tshock.tp.tppotion tshock.tp.rod
  tshock.tp.magicconch tshock.tp.demonconch
  # chat
  tshock.canchat tshock.whisper tshock.partychat tshock.thirdperson tshock.sendemoji
  # misc
  tshock.synclocalarea tshock.respawn tshock.journey.research
  # stop anti-grief from undoing normal play (fast mining, bombs, liquids, paint…)
  tshock.ignore.removetile tshock.ignore.placetile tshock.ignore.liquid
  tshock.ignore.projectile tshock.ignore.paint tshock.ignore.damage
  tshock.ignore.itemstack tshock.ignore.npcbuff tshock.ignore.hp tshock.ignore.mp
)

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo ./scripts/perms.sh" >&2
  exit 1
fi

echo "==> Stopping the server (the world is saved)"
docker compose stop terraria
trap 'echo "==> Starting the server"; docker compose up -d terraria' EXIT

echo "==> Unlocking normal gameplay for all players"
python3 - "${PERMS[@]}" <<'PY'
import sys, sqlite3
db = sqlite3.connect("data/tshock/tshock.sqlite")
row = db.execute("SELECT Commands FROM GroupList WHERE GroupName='guest'").fetchone()
if row is None:
    sys.exit("No 'guest' group found — has the server been started at least once?")
perms = [p for p in (row[0] or "").split(",") if p]
added = [p for p in sys.argv[1:] if p not in perms]
db.execute("UPDATE GroupList SET Commands=? WHERE GroupName='guest'", (",".join(perms + added),))
db.commit()
print(f"  {len(added)} permissions added ({len(sys.argv) - 1 - len(added)} were already set).")
PY
