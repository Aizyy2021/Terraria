"""Small helpers shared by the Discord status service and the watchdog."""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_env():
    env = {}
    try:
        lines = (ROOT / ".env").read_text().splitlines()
    except OSError:
        return env
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            env[key.strip()] = value
    return env


def request(method, url, payload):
    """Sends a webhook request, waiting out rate limits. Returns (status, json)."""
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


def post(webhook, payload):
    """Posts a message and returns its id, or None."""
    code, data = request("POST", f"{webhook}?wait=true", payload)
    return data.get("id") if code == 200 else None


def edit(webhook, message_id, payload):
    """Edits a message the webhook posted. Returns the HTTP status."""
    code, _ = request("PATCH", f"{webhook}/messages/{message_id}", payload)
    return code
