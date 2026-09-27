"""Posts player joins/leaves from the TShock log to a Discord webhook.

Runs in its own small container (see the `discord` service in
docker-compose.yml) and only reads the log files, so it can't affect the
game server. Player IPs are never sent to Discord.
"""
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
LOG_DIR = "/logs"
MAX_PLAYERS = os.environ.get("MAX_PLAYERS", "8")
SERVER_NAME = os.environ.get("SERVER_NAME", "Terraria")

JOIN = re.compile(
    r"INFO: (?P<name>.+) \([^)]*\) from '[^']*' group(?: from '[^']*')? joined\. \((?P<count>\d+)/(?P<max>\d+)\)$"
)
LEAVE = re.compile(r"INFO: (?P<name>.+) disconnected\.$")

GREEN, RED, BLUE = 0x3BA55C, 0xED4245, 0x5865F2


def post(title, color, footer=None):
    embed = {"title": title, "color": color}
    if footer:
        embed["footer"] = {"text": footer}
    body = json.dumps({
        "username": SERVER_NAME,
        "embeds": [embed],
        "allowed_mentions": {"parse": []},  # player names can't ping anyone
    }).encode()
    for _ in range(3):
        req = urllib.request.Request(
            WEBHOOK, data=body, headers={"Content-Type": "application/json", "User-Agent": "terraria-notify"}
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited — wait as Discord asks, then retry
                time.sleep(float(e.headers.get("Retry-After", "2")))
                continue
            print(f"Discord returned {e.code}: {e.read()[:200]!r}", flush=True)
            return
        except OSError as e:
            print(f"Could not reach Discord: {e}", flush=True)
            time.sleep(5)


def newest_log():
    logs = glob.glob(os.path.join(LOG_DIR, "*.log"))
    return max(logs, key=os.path.getmtime) if logs else None


def main():
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL is not set — run scripts/discord.sh. Idling.", flush=True)
        while True:
            time.sleep(3600)

    print("Watching TShock logs for joins and leaves.", flush=True)
    current, handle, online = None, None, set()
    first = True

    while True:
        latest = newest_log()
        if latest and latest != current:
            if handle:
                handle.close()
            current, handle = latest, open(latest, encoding="utf-8", errors="replace")
            online.clear()
            if first:
                handle.seek(0, os.SEEK_END)  # don't replay old history on startup
            else:
                post("🟢 Server is online", BLUE)  # a new log file means the server restarted
            first = False

        line = handle.readline() if handle else ""
        if not line:
            time.sleep(1)
            continue
        line = line.rstrip("\n")

        if m := JOIN.search(line):
            name = m["name"]
            online.add(name)
            post(f"➕ {name} joined", GREEN, f"{m['count']}/{m['max']} online")
        elif (m := LEAVE.search(line)) and m["name"] in online:
            name = m["name"]
            online.discard(name)
            post(f"➖ {name} left", RED, f"{len(online)}/{MAX_PLAYERS} online")


if __name__ == "__main__":
    main()
