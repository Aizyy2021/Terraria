"""Restarts the Terraria server when it freezes.

Docker already restarts the container if the server *crashes*, but a frozen
server keeps running while nobody can join. Every minute this knocks on the
game port the way a player would (a Terraria connect request) and waits for
the game to answer. Any answer — even "wrong version" — means the game loop
is alive. After 2 missed answers in a row it saves diagnostics to
data/incidents/ and restarts the container.

It also notices when the server crashed and Docker restarted it.

If a Discord webhook is set up (scripts/discord.sh), each incident posts one
alert message below the status embed, which is then edited to "recovered"
once players can join again — so the channel doesn't fill up.

It does nothing while the container is stopped on purpose
(`docker compose stop`). Runs as the `terraria-watchdog` systemd service,
installed by scripts/watchdog.sh.
"""
import datetime
import socket
import subprocess
import time
from pathlib import Path

from discord_webhook import edit, post, read_env

ROOT = Path(__file__).resolve().parent.parent
INCIDENTS = ROOT / "data" / "incidents"

INTERVAL = 120         # seconds between checks (each one adds a "was booted" line to the log)
TIMEOUT = 10           # seconds to wait for the game to answer
FAILS_BEFORE_RESTART = 2
STARTUP_GRACE = 240    # seconds to leave a freshly (re)started server alone
KEEP_INCIDENTS = 20
STILL_DOWN_AFTER = 600 # seconds before an alert escalates to "still down"

RED, ORANGE, GREEN = 0xED4245, 0xF0A232, 0x3BA55C


def read_port():
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("SERVER_PORT="):
                return int(line.split("=", 1)[1].strip().strip("'\""))
    except (OSError, ValueError):
        pass
    return 7777


def connect_request():
    """A Terraria 'ConnectRequest' packet (type 1).

    The version string doesn't need to match: a live server answers a wrong
    version with a kick message, which is still an answer.
    """
    version = b"Terraria0"
    payload = bytes([1, len(version)]) + version          # type, 7-bit length, string
    return (len(payload) + 2).to_bytes(2, "little") + payload


def game_answers(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT) as s:
            s.settimeout(TIMEOUT)
            s.sendall(connect_request())
            return len(s.recv(64)) > 0
    except OSError:
        return False


def docker(*args, timeout=120):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def container_state():
    """Returns (running, started_at_unix or None, docker_restart_count)."""
    out = docker("inspect", "-f", "{{.State.Running}} {{.State.StartedAt}} {{.RestartCount}}",
                 "terraria", timeout=15).stdout.split()
    if len(out) != 3:
        return False, None, 0
    try:
        ts = datetime.datetime.strptime(out[1][:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        ts = None
    return out[0] == "true", ts, int(out[2]) if out[2].isdigit() else 0


def save_incident(reason):
    INCIDENTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = INCIDENTS / f"{stamp}.txt"
    parts = [f"Watchdog restart at {stamp}\nReason: {reason}\n"]
    for title, cmd in [
        ("container stats", ["docker", "stats", "--no-stream", "terraria"]),
        ("processes", ["docker", "top", "terraria"]),
        ("memory", ["free", "-m"]),
        ("load", ["uptime"]),
        ("last 300 log lines", ["docker", "logs", "--tail", "300", "terraria"]),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            parts.append(f"\n===== {title} =====\n{r.stdout}{r.stderr}")
        except (OSError, subprocess.TimeoutExpired) as e:
            parts.append(f"\n===== {title} =====\n(failed: {e})\n")
    path.write_text("".join(parts))
    for old in sorted(INCIDENTS.glob("*.txt"))[:-KEEP_INCIDENTS]:
        old.unlink()
    return path


class Alerts:
    """One Discord message per incident, edited as the incident progresses."""

    def __init__(self):
        env = read_env()
        self.webhook = env.get("DISCORD_WEBHOOK_URL", "")
        self.name = env.get("DISCORD_TITLE") or "Terraria Server"
        self.incident = None   # {"id", "start", "kind", "report", "escalated"}

    def _send(self, title, text, color, fields):
        if not self.webhook:
            return None
        payload = {
            "username": self.name,
            "embeds": [{"title": title, "description": text, "color": color, "fields": fields,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}],
            "allowed_mentions": {"parse": []},
        }
        if self.incident and self.incident.get("id"):
            edit(self.webhook, self.incident["id"], payload)
            return self.incident["id"]
        return post(self.webhook, payload)

    def _fields(self, extra=()):
        i = self.incident
        fields = [{"name": "Detected", "value": f"<t:{int(i['start'])}:t> · <t:{int(i['start'])}:R>", "inline": True}]
        if i.get("report"):
            fields.append({"name": "Report", "value": f"`data/incidents/{i['report']}`", "inline": True})
        return fields + list(extra)

    def opened(self, kind, report):
        if self.incident:
            return
        self.incident = {"kind": kind, "start": time.time(), "report": report, "escalated": False, "id": None}
        if kind == "freeze":
            title, text = "Server froze", "Not answering players. Restarting automatically…"
        else:
            title, text = "Server crashed", "The server process stopped. Docker is restarting it automatically…"
        self.incident["id"] = self._send(f"🔴  {title}", text, RED, self._fields())

    def still_down(self):
        i = self.incident
        if not i or i["escalated"] or time.time() - i["start"] < STILL_DOWN_AFTER:
            return
        i["escalated"] = True
        self._send("🟠  Server is still down",
                   "The automatic restart didn't bring it back. Someone needs to check the VPS.",
                   ORANGE, self._fields())

    def recovered(self):
        i = self.incident
        if not i:
            return
        minutes = max(1, round((time.time() - i["start"]) / 60))
        cause = "a freeze" if i["kind"] == "freeze" else "a crash"
        self._send("🟢  Server recovered",
                   f"Back online after {minutes} min. Restarted automatically after {cause}.",
                   GREEN, self._fields([{"name": "Recovered", "value": f"<t:{int(time.time())}:R>", "inline": True}]))
        self.incident = None


def main():
    port = read_port()
    alerts = Alerts()
    fails = 0
    _, _, seen_restarts = container_state()
    print(f"Watching the Terraria server on port {port}.", flush=True)

    while True:
        time.sleep(INTERVAL)
        try:
            running, started, restarts = container_state()
        except (OSError, subprocess.TimeoutExpired):
            continue

        # Docker restarted the container on its own: the server crashed.
        if restarts > seen_restarts:
            seen_restarts = restarts
            report = save_incident("the server process crashed; Docker restarted it")
            print(f"Server crashed — saved {report.name}.", flush=True)
            alerts.opened("crash", report.name)

        if not running:
            fails = 0  # stopped on purpose, or Docker is already restarting it
            alerts.still_down()
            continue
        if started and time.time() - started < STARTUP_GRACE:
            continue   # still loading the world

        if game_answers(port):
            if fails:
                print("Server is answering again.", flush=True)
            fails = 0
            alerts.recovered()
            continue

        alerts.still_down()
        fails += 1
        print(f"No answer from the server ({fails}/{FAILS_BEFORE_RESTART}).", flush=True)
        if fails < FAILS_BEFORE_RESTART:
            continue

        report = save_incident(f"no answer on port {port} for {FAILS_BEFORE_RESTART} checks in a row")
        print(f"Server is frozen — saved {report.name}, restarting.", flush=True)
        alerts.opened("freeze", report.name)
        try:
            r = docker("compose", "--project-directory", str(ROOT), "restart", "terraria", timeout=180)
            if r.returncode != 0:
                print(f"Restart failed: {r.stderr.strip()}", flush=True)
        except subprocess.TimeoutExpired:
            print("Restart is taking too long; will check again next round.", flush=True)
        fails = 0


if __name__ == "__main__":
    main()
