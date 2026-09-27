# Terraria Server

A 24/7 **TShock** server for 6–8 players: a new **Expert** world, no mods, nightly backups.

| | |
|---|---|
| **World** | Medium, Expert, created on first start |
| **Players** | 8 max, password protected |
| **Backups** | TShock snapshot every 30 min, full archive every night (kept 14 days) |
| **Cost** | ~€4–6 / month for the VPS |

---

## For players: how to join

You only need normal Terraria (Steam or GOG). Nothing else to install.

1. Open Terraria and choose **Multiplayer → Join via IP**.
2. Pick a character. Any **Classic** character works, but Journey characters can't join Expert worlds.
3. Enter the server **IP**, port **7777**, and the **password**.

> "Wrong version" message? Make sure Terraria is up to date. If it is, the server needs updating (see [Updating](#updating)).

---

## For the host: setting it up

### 1. Rent a VPS
Any provider works. A good choice is **Hetzner Cloud**, with these settings:
- **Type:** the cheapest shared x86 plan with **2 vCPU / 4 GB RAM**
- **Location:** closest to your group
- **Image:** Ubuntu 24.04
- **SSH key:** add yours (recommended), or use the root password they email you

Copy the server's **IPv4 address**.

### 2. Log in and install
From a terminal (Windows: PowerShell):

```bash
ssh root@YOUR_SERVER_IP
```

Then on the server:

```bash
git clone https://github.com/aizyy2021/terraria.git
cd terraria
sudo ./scripts/setup.sh
```

The script installs Docker, opens the firewall, asks you to choose a server password, creates the world and starts the server. When it finishes, it prints the address your friends should use.

To change the world name, size or player count, edit `.env` **before** running setup (`cp .env.example .env && nano .env`).

### 3. Let everyone play normally
TShock is made for public servers, so out of the box it blocks lots of normal gameplay
(wormhole potions, pylons, summoning bosses, fast mining…) for non-admins. Unlock it all:

```bash
sudo ./scripts/perms.sh
```

Cheats stay admin-only: `/item`, `/give`, `/tp`, `/godmode`, `/time` and similar.

### 4. Become admin
The setup script prints an **admin setup code**. Then, in-game:

```
/setup 1234567                       ← the code from the script
/user add YourName YourPassword owner
/login YourName YourPassword
/setup                               ← turns the setup code off
```

Log in with `/login` each time you join to get your admin powers.

---

## Everyday commands
Run these on the VPS, inside the `terraria` folder.

| Task | Command |
|---|---|
| Server status | `docker compose ps` |
| Live log | `docker compose logs -f` |
| Server console | `docker attach terraria` (leave with **Ctrl+P, Ctrl+Q**, not Ctrl+C) |
| Restart | `docker compose restart` |
| Stop / start | `docker compose stop` / `docker compose up -d` |
| Backup now | `sudo ./scripts/backup.sh` |
| Restore a backup | `sudo ./scripts/restore.sh backups/terraria_<date>.tar.gz` |
| Block a spammer's IP | `sudo ./scripts/block-ip.sh 1.2.3.4` |

The server saves the world automatically and when it's stopped.

Useful in-game admin commands: `/kick`, `/ban add`, `/save`, `/time day`, `/butcher`, `/help`.

---

## Changing settings
Edit `.env` (password, max players), then re-run:

```bash
sudo ./scripts/setup.sh
```

`WORLD_SIZE` and `DIFFICULTY` only apply when a world is **first** created. To start a fresh world, change `WORLD_NAME` and re-run setup. The old world file stays in `data/worlds/`.

Advanced TShock settings live in `data/tshock/config.json`.

---

## Plugins (optional QoL)
One command installs three small plugins, lets every player use them and the normal
vanilla actions TShock blocks for guests (wormhole potions, pylons, summoning bosses,
assigning NPC houses…), then restarts the server:

```bash
git pull && sudo ./scripts/plugins.sh
```

| Command | What it does |
|---|---|
| `/back` | Teleport to where you last died |
| `/tpa Name` · `/atp` · `/dtp` | Ask to teleport to a friend · accept · deny |
| `/npchome` | Send town NPCs back to their houses |

Remove them again with `sudo ./scripts/plugins.sh --remove`.

---

## Discord notifications (optional)
Posts "➕ Name joined", "➖ Name left" and "🟢 Server is online" to a Discord channel.
Player IPs are never sent.

1. In Discord: channel **⚙ Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
2. On the VPS:
   ```bash
   git pull && sudo ./scripts/discord.sh
   ```
   Paste the URL when asked. A test message confirms it works.

Turn it off with `sudo ./scripts/discord.sh --off`. The game server is never restarted for this.

---

## Updating
When Terraria gets a patch, TShock usually follows within a few days.

1. Find the newest version on the [TShock releases page](https://github.com/Pryaxis/TShock/releases).
2. Set it in `.env`, for example `TSHOCK_VERSION=6.2.1`.
3. Apply it:
   ```bash
   sudo ./scripts/backup.sh
   docker compose pull && docker compose up -d
   ```

---

## Where things are

```
data/worlds/        your world (.wld)
data/tshock/        config, player accounts, logs, 30-min snapshots
backups/            nightly archives
.env                your settings (not committed; contains the password)
```
