# Minecraft SIEM Lab

Run your own Minecraft servers from a web dashboard on your PC, and watch them with Wazuh, a free security monitoring tool (SIEM).

- **Dashboard** at http://localhost:5000: create worlds, start and stop them, change settings, manage the whitelist, take backups. Each world is its own server in Docker.
- **Friends join** through a playit.gg tunnel. Only the game port is ever exposed; the dashboard stays on your PC.
- **Wazuh** alerts on failed dashboard logins, players who aren't whitelisted trying to join, crashes, and every admin action.

Works on Windows (Docker Desktop) and Linux. macOS should work like Windows but hasn't been tested.

## Quick start

You need [Git](https://git-scm.com/downloads) and Docker: [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows, or Docker Engine with the Compose plugin on Linux. Make sure Docker is **running** before you start.

1. **Clone the repo** and go into it:
   ```sh
   git clone https://github.com/dbaugustin/minecraft-siem-lab.git
   cd minecraft-siem-lab
   ```
2. **Make your settings file.** Copy `.env.example` to `.env` (Windows PowerShell: `Copy-Item .env.example .env`, Linux: `cp .env.example .env`).
3. **Fill in two secrets** in `.env`. Docker can generate both, so you don't need Python installed:
   ```sh
   docker compose run --rm dashboard python -c "import secrets; print(secrets.token_hex(32))"
   docker compose run --rm dashboard python scripts/hash_password.py
   ```
   Paste the first into `FLASK_SECRET_KEY=`. The second asks for a password (12+ characters) and prints a hash; paste it in **single quotes**: `DASHBOARD_ADMIN_PASSWORD_HASH='$argon2id$...'`.
4. **Windows only:** set `HOST_WORLDS_DIR` in `.env` to your clone's `worlds` folder as Docker sees it. For a clone at `C:\Users\you\minecraft-siem-lab`:
   ```
   HOST_WORLDS_DIR=/run/desktop/mnt/host/c/Users/you/minecraft-siem-lab/worlds
   ```
5. **Start it:**
   ```sh
   docker compose up -d --build
   ```
6. **Open http://localhost:5000**, log in as `admin` with your password, and create a world. The first start of a Spigot world compiles the server, which takes **10 to 40 minutes**; the world page shows the build log while it runs.

To let friends join, point a [playit.gg](https://playit.gg) tunnel at the world's port. See [docs/setup.md](docs/setup.md#let-friends-join-playitgg).

## After a reboot

1. Start **Docker Desktop** (Windows) and wait until it says it's running. On Linux, Docker starts on its own.
2. That's usually it. The dashboard and every world that was running come back by themselves. If the dashboard doesn't, run `docker compose up -d` in the repo folder.
3. If you use Wazuh, start it too: `docker compose up -d` in `wazuh-docker/single-node`. See [docs/wazuh.md](docs/wazuh.md#after-a-reboot).

## Guides

| Guide | What's in it |
|---|---|
| [docs/setup.md](docs/setup.md) | Full install for Windows and Linux, every `.env` setting, playit.gg, troubleshooting |
| [docs/worlds.md](docs/worlds.md) | Creating worlds, settings, importing an existing world, backups, restoring, deleting |
| [docs/wazuh.md](docs/wazuh.md) | Running Wazuh, loading this repo's rules, connecting the agent, seeing alerts |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit, and the security design |
| [wazuh/README.md](wazuh/README.md) | Every Wazuh rule, what fires it, and how to test it |

## Features

- [x] Create, delete, start, stop and restart worlds, each as its own server container
- [x] Edit per-world settings (version, memory, difficulty, MOTD, ...)
- [x] Server log, online players and whitelist per world (RCON)
- [x] Manual and scheduled backups with retention
- [x] CPU and RAM per world
- [x] Auto-restart on crash
- [x] Login with argon2-hashed password, sessions, CSRF protection and lockout
- [x] Audit log of every dashboard action, with Wazuh rules
- [ ] Console and operator controls from the dashboard (in progress)
- [ ] Upload a world as a .zip from the dashboard (in progress)
- [ ] Link to Wazuh from the dashboard (in progress)

## Repository layout

```
docker-compose.yml   The dashboard service and the mclab network
.env.example         Every setting, with comments; copy to .env
dashboard/           Flask app (mcdash/) and its tests
wazuh/               Wazuh decoders, rules, agent config and sample logs
docs/                Guides
worlds/              One folder per world (created by the dashboard, not committed)
backups/             World backups (not committed)
logs/                Dashboard audit log (not committed)
```
