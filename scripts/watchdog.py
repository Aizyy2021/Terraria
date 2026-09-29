"""Restarts the Terraria server when it freezes.

Docker already restarts the container if the server *crashes*, but a frozen
server keeps running while nobody can join. Every minute this knocks on the
game port the way a player would (a Terraria connect request) and waits for
the game to answer. Any answer — even "wrong version" — means the game loop
is alive. After 3 missed answers in a row it saves diagnostics to
data/incidents/ and restarts the container.

It does nothing while the container is stopped on purpose
(`docker compose stop`). Runs as the `terraria-watchdog` systemd service,
installed by scripts/watchdog.sh.
"""
import datetime
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCIDENTS = ROOT / "data" / "incidents"

INTERVAL = 60          # seconds between checks
TIMEOUT = 10           # seconds to wait for the game to answer
FAILS_BEFORE_RESTART = 3
STARTUP_GRACE = 240    # seconds to leave a freshly (re)started server alone
KEEP_INCIDENTS = 20


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
    """Returns (running, started_at_unix or None)."""
    out = docker("inspect", "-f", "{{.State.Running}} {{.State.StartedAt}}", "terraria", timeout=15).stdout.split()
    if len(out) != 2:
        return False, None
    started = out[1][:19]
    try:
        ts = datetime.datetime.strptime(started, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        ts = None
    return out[0] == "true", ts


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


def main():
    port = read_port()
    fails = 0
    print(f"Watching the Terraria server on port {port}.", flush=True)

    while True:
        time.sleep(INTERVAL)
        running, started = container_state()
        if not running:
            fails = 0  # stopped on purpose, or Docker is already restarting it
            continue
        if started and time.time() - started < STARTUP_GRACE:
            continue   # still loading the world

        if game_answers(port):
            if fails:
                print("Server is answering again.", flush=True)
            fails = 0
            continue

        fails += 1
        print(f"No answer from the server ({fails}/{FAILS_BEFORE_RESTART}).", flush=True)
        if fails < FAILS_BEFORE_RESTART:
            continue

        report = save_incident(f"no answer on port {port} for {FAILS_BEFORE_RESTART} checks in a row")
        print(f"Server is frozen — saved {report.name}, restarting.", flush=True)
        try:
            r = docker("compose", "--project-directory", str(ROOT), "restart", "terraria", timeout=180)
            if r.returncode != 0:
                print(f"Restart failed: {r.stderr.strip()}", flush=True)
        except subprocess.TimeoutExpired:
            print("Restart is taking too long; will check again next round.", flush=True)
        fails = 0


if __name__ == "__main__":
    main()
