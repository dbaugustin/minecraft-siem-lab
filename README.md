# Minecraft SIEM Lab

A self-hosted Minecraft server managed by a localhost-only Flask dashboard, with the game server and the dashboard both monitored by Wazuh SIEM.

> Status: scaffold. Sections marked _TODO_ get filled in as features are built.

## Architecture

```
            friends (internet)
                   │
             playit.gg tunnel
                   │  TCP 25565 only
┌──────────────────▼──────────────────────────── server box ──┐
│  ┌──────────────────────┐   RCON :25575 (compose network)    │
│  │ minecraft            │◄───────────────┐                   │
│  │ itzg/minecraft-server│                │                   │
│  └─────────┬────────────┘   ┌────────────┴─────────┐         │
│            │ Docker SDK ───►│ dashboard (Flask)    │◄── you, │
│            │ (docker.sock)  │ 127.0.0.1:5000       │  browser│
│            ▼                └──────────┬───────────┘  on box │
│   ./data/logs/latest.log    ./logs/audit.jsonl               │
│            └──────────┬────────────────┘                     │
│                 Wazuh agent (localfile) ──► Wazuh manager    │
└──────────────────────────────────────────────────────────────┘
```

_TODO: replace with a proper diagram._

## Security design

- **Dashboard is localhost-only.** Compose publishes it as `127.0.0.1:5000`, so it is unreachable from the LAN or the internet. It is never tunneled. Only the game port (25565) is exposed, through playit.gg.
- **RCON is internal.** Port 25575 exists only on the Docker compose network and is not published on the host.
- **Secrets live in `.env`**, which is gitignored. `.env.example` documents every variable.
- **Game access control:** online mode (Microsoft account verification) plus an enforced whitelist.
- **Docker socket:** the dashboard mounts `/var/run/docker.sock` to control the server container. That is root-equivalent on the host, which is part of why the dashboard stays local and behind a login.
- _TODO: login (argon2 hashing, sessions, CSRF), login rate limiting/lockout, audit log format._

## Setup

1. Install Docker and Docker Compose on the server.
2. Clone this repo and copy the env file:
   ```sh
   cp .env.example .env
   ```
   Fill in `RCON_PASSWORD`, `FLASK_SECRET_KEY`, and the whitelist.
3. Copy the existing world folder to `./data/world`.
4. Start everything:
   ```sh
   docker compose up -d --build
   ```
5. Open http://localhost:5000 on the server box.
6. Point the playit.gg tunnel at `localhost:25565`.

## Features

- [ ] Start / stop / restart the server (Docker SDK)
- [ ] Live server console/log view
- [ ] Online player list and whitelist management (RCON)
- [ ] Manual timestamped world backups
- [ ] Login with hashed passwords, sessions, CSRF protection
- [ ] Scheduled backups with retention
- [ ] Auto-restart on crash
- [ ] Container CPU/RAM stats

## Wazuh integration

_TODO: agent `localfile` config, custom decoders and rules, and screenshots of each rule firing._

Planned rules:
- Failed dashboard logins and brute-force attempts
- Non-whitelisted players trying to join
- Unexpected server stops and crash loops
- Admin actions (whitelist changes, server stops)

## Repository layout

```
docker-compose.yml   Minecraft + dashboard services
.env.example         Every config variable, no real values
dashboard/           Flask app (placeholder for now)
data/                Server data and world (gitignored, created at runtime)
backups/             World backups (gitignored)
logs/                Dashboard audit log (gitignored)
```
