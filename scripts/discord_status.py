"""Keeps one Discord message up to date with the Terraria server's status.

Instead of posting a new message for every event, it posts a single embed
once and then edits it: online/offline, players online, and recent joins and
leaves with timestamps. Runs on the VPS as the `terraria-discord` systemd
service (installed by scripts/discord.sh) and only reads the TShock logs and
Docker's container state, so it can't affect the game server.

Player IPs are never sent to Discord.
"""
import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "tshock" / "logs"
STATE_FILE = ROOT / "data" / "discord-status.json"

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - [^:]+: \w+: (.*)$")
JOIN = re.compile(r"^(?P<name>.+) \([^)]*\) from '[^']*' group(?: from '[^']*')? joined\. \(\d+/\d+\)$")
LEAVE = re.compile(r"^(?P<name>.+) disconnected\.$")

GREEN, RED = 0x3BA55C, 0xED4245
MAX_EVENTS = 8
POLL_SECONDS = 2
STATUS_EVERY = 15
MIN_EDIT_GAP = 3


def read_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            env[key.strip()] = value
    return env


ENV = read_env()
WEBHOOK = ENV.get("DISCORD_WEBHOOK_URL", "")
TITLE = ENV.get("DISCORD_TITLE") or "Terraria Server"
MAX_PLAYERS = ENV.get("MAX_PLAYERS", "8")
ADDRESS = ENV.get("SERVER_ADDRESS", "")
PORT = ENV.get("SERVER_PORT", "7777")


# ── state ────────────────────────────────────────────────────────────────

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


# ── docker ───────────────────────────────────────────────────────────────

def iso_to_unix(value):
    # Docker gives nanosecond precision, e.g. 2026-09-27T16:24:07.123456789Z
    value = re.sub(r"\.(\d{6})\d*", r".\1", value).replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def server_status():
    """Returns (running, since_unix) for the terraria container."""
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}} {{.State.StartedAt}} {{.State.FinishedAt}}", "terraria"],
            capture_output=True, text=True, timeout=10,
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(out) != 3:
        return (False, None)
    running = out[0] == "true"
    since = iso_to_unix(out[1] if running else out[2])
    return (running, since if since and since > 0 else None)


# ── discord ──────────────────────────────────────────────────────────────

def escape(name):
    return re.sub(r"([\\*_`~|>])", r"\\\1", name)


def build_embed(state):
    running = state.get("running", False)
    since = state.get("since")
    online = state.get("online", [])

    status = "🟢  **Online**" if running else "🔴  **Offline**"
    if since:
        status += f"  ·  since <t:{since}:R>"

    fields = []
    if ADDRESS:
        fields.append({"name": "Address", "value": f"`{ADDRESS}:{PORT}`", "inline": True})
    fields.append({"name": "Players", "value": f"{len(online) if running else 0} / {MAX_PLAYERS}", "inline": True})
    fields.append({
        "name": "Online now",
        "value": ", ".join(escape(n) for n in online) if running and online else "*Nobody*",
        "inline": False,
    })

    lines = []
    for e in reversed(state.get("events", [])):
        when = f"<t:{e['t']}:R>"
        if e["kind"] == "join":
            lines.append(f"`+`  **{escape(e['name'])}** joined · {when}")
        elif e["kind"] == "leave":
            lines.append(f"`−`  **{escape(e['name'])}** left · {when}")
        elif e["kind"] == "up":
            lines.append(f"`↑`  Server started · {when}")
        elif e["kind"] == "down":
            lines.append(f"`↓`  Server stopped · {when}")
    fields.append({"name": "Recent activity", "value": "\n".join(lines) or "*Nothing yet*", "inline": False})

    return {
        "title": TITLE,
        "description": status,
        "color": GREEN if running else RED,
        "fields": fields,
        "footer": {"text": "Last updated"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def request(method, url, payload):
    body = json.dumps(payload).encode()
    for _ in range(5):
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Content-Type": "application/json", "User-Agent": "terraria-status",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                return resp.status, json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", "2")))
                continue
            return e.code, {}
        except OSError as e:
            print(f"Could not reach Discord: {e}", flush=True)
            time.sleep(5)
    return None, {}


def publish(state):
    payload = {"username": TITLE, "embeds": [build_embed(state)], "allowed_mentions": {"parse": []}}
    msg_id = state.get("message_id")
    if msg_id:
        code, _ = request("PATCH", f"{WEBHOOK}/messages/{msg_id}", payload)
        if code == 200:
            return
        if code not in (404,):  # anything but "message deleted": try again later
            print(f"Editing the status message failed ({code}).", flush=True)
            return
    code, data = request("POST", f"{WEBHOOK}?wait=true", payload)
    if code == 200 and data.get("id"):
        state["message_id"] = data["id"]
        print("Posted a new status message.", flush=True)
    else:
        print(f"Posting the status message failed ({code}).", flush=True)


# ── log reading ──────────────────────────────────────────────────────────

def newest_log():
    logs = glob.glob(str(LOG_DIR / "*.log"))
    return max(logs, key=os.path.getmtime) if logs else None


def local_offset(path):
    """Seconds to add to a log timestamp to get Unix time.

    TShock writes timestamps in the container's local time, which may not be
    the host's, so the offset is measured: the file's last write time vs the
    timestamp on its last line, rounded to the nearest 15 minutes.
    """
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 4096))
            tail = f.read().decode("utf-8", "replace").splitlines()
        for line in reversed(tail):
            if m := LINE.match(line):
                naive = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                diff = os.path.getmtime(path) - naive.timestamp()
                return round(diff / 900) * 900
    except OSError:
        pass
    return 0


def add_event(state, kind, when, name=None):
    event = {"kind": kind, "t": int(when)}
    if name:
        event["name"] = name
    events = state.setdefault("events", [])
    events.append(event)
    events.sort(key=lambda e: e["t"])  # status checks can lag the log by a few seconds
    del events[:-MAX_EVENTS]


def handle_line(state, line, offset):
    m = LINE.match(line)
    if not m:
        return False
    when = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() + offset
    message = m[2]
    online = state.setdefault("online", [])
    if j := JOIN.match(message):
        if j["name"] not in online:
            online.append(j["name"])
        add_event(state, "join", when, j["name"])
        return True
    if (l := LEAVE.match(message)) and l["name"] in online:  # ignores bots that never fully joined
        online.remove(l["name"])
        add_event(state, "leave", when, l["name"])
        return True
    return False


# ── main loop ────────────────────────────────────────────────────────────

def main():
    if not WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK_URL is not set in .env — run scripts/discord.sh.")

    state = load_state()
    handle, current, offset = None, None, 0
    dirty, last_edit, last_status = True, 0.0, 0.0
    print("Keeping the Discord status message up to date.", flush=True)

    while True:
        now = time.time()

        # Server up/down, straight from Docker.
        if now - last_status >= STATUS_EVERY or last_status == 0:
            last_status = now
            status = server_status()
            if status is not None:
                running, since = status
                if running != state.get("running"):
                    if "running" in state:  # skip the very first check after install
                        add_event(state, "up" if running else "down", since or now)
                    if not running:
                        state["online"] = []
                    dirty = True
                if since != state.get("since"):
                    dirty = True
                state["running"], state["since"] = running, since

        # A new log file means the server started a new session.
        latest = newest_log()
        if latest and latest != current:
            if handle:
                handle.close()
            current = latest
            handle = open(current, "rb")
            offset = local_offset(current)
            if state.get("log") == os.path.basename(current):
                handle.seek(state.get("pos", 0))  # resume where we left off
            else:
                state["online"] = []  # fresh session: rebuild from the start of the log
            state["log"] = os.path.basename(current)

        # New log lines.
        if handle:
            while raw := handle.readline():
                if not raw.endswith(b"\n"):  # partially written; read it again next time
                    handle.seek(-len(raw), os.SEEK_CUR)
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                dirty |= handle_line(state, line, offset)
            state["pos"] = handle.tell()

        if dirty and time.time() - last_edit >= MIN_EDIT_GAP:
            publish(state)
            save_state(state)
            dirty, last_edit = False, time.time()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
