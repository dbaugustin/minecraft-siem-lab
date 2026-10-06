# Minecraft SIEM Lab

Self-hosted Minecraft servers (one per world) managed by a localhost-only Flask dashboard, with the game servers and the dashboard all monitored by Wazuh SIEM.

> Status: scaffold. Sections marked _TODO_ get filled in as features are built.

## Architecture

```
               friends (internet)
                      │
                playit.gg tunnels
                      │  one game port per world (25565, 25566, ...)
┌─────────────────────▼───────────────────────────── server box ──┐
│  ┌───────────────┐ ┌───────────────┐                            │
│  │ mc-survival   │ │ mc-creative   │ ...  itzg/minecraft-server │
│  └──────▲────────┘ └──────▲────────┘      one container / world │
│         │ RCON :25575 on the internal "mclab" network           │
│         │                 │                                     │
│  ┌──────┴─────────────────┴─────┐                               │
│  │ dashboard (Flask)            │◄── you, browser on the box    │
│  │ 127.0.0.1:5000               │                               │
│  │ creates/recreates world      │                               │
│  │ containers via docker.sock   │                               │
│  └──────────────┬───────────────┘                               │
│  worlds/*/data/logs/latest.log    logs/audit.jsonl              │
│                 └──────┬───────────────┘                        │
│              Wazuh agent (localfile) ──► Wazuh manager          │
└─────────────────────────────────────────────────────────────────┘
```

_TODO: replace with a proper diagram._

## Worlds

Each world is its own Minecraft server: a separate `itzg/minecraft-server` container named `mc-<world>`. They are not defined in `docker-compose.yml`. The dashboard creates them through the Docker SDK, so adding a world is a dashboard action rather than a config edit.

Every world lives in its own directory:

```
worlds/
  survival/
    world.json        settings the dashboard edits
    data/             the container's /data (world/, server.properties, logs/)
  creative/
    ...
```

`world.json` is the source of truth for a world's settings. A sketch of its shape (final fields TBD while building the dashboard):

```json
{
  "name": "survival",
  "type": "SPIGOT",
  "version": "1.21.1",
  "memory": "2G",
  "port": 25565,
  "rcon_password": "<generated per world>",
  "properties": {
    "difficulty": "normal",
    "max-players": 10,
    "motd": "David's survival world",
    "pvp": true
  },
  "whitelist": ["player1", "player2"],
  "ops": ["player1"]
}
```

**How changing a setting works:** the dashboard saves `world.json`, then recreates the world's container with the matching itzg environment variables (`VERSION`, `MEMORY`, `DIFFICULTY`, `MOTD`, ...). The itzg image rewrites `server.properties` from those variables on every start, so the container config stays the single place settings come from. World data in `data/` is a bind mount and survives the recreate. Whitelist changes on a running server go through RCON so they apply without a restart.

Every world container gets the same fixed hardening regardless of `world.json`: online mode on, whitelist enforced, RCON enabled with a per-world random password and its port never published, joined to the `mclab` network, and labelled `mc-siem-lab.world=<name>` so the dashboard only ever touches its own containers.

**Ports:** each world needs its own host game port (25565, 25566, ...) and its own playit.gg tunnel entry pointing at it.

**Server software:** new worlds default to Spigot (`MC_DEFAULT_TYPE` in `.env`); the type stays editable per world. Spigot publishes no ready-made jar, so the dashboard sets itzg's `BUILD_FROM_SOURCE=TRUE` and the container builds Spigot with BuildTools on its first start and after a version change. That takes several minutes and needs network access to hub.spigotmc.org; the world page shows the build output (`data/spigot_build.log`) until the server's own log appears. The built jar is kept in `data/` and reused on later starts. Right after a new Minecraft release, `LATEST` can fail until Spigot catches up; pin a version like `1.21.1` if that happens.

## Security design

- **Dashboard is localhost-only.** Compose publishes it as `127.0.0.1:5000`, so it is unreachable from the LAN or the internet. It is never tunneled. Only the game port (25565) is exposed, through playit.gg.
- **RCON is internal.** Each world's RCON port (25575) exists only on the `mclab` Docker network and is never published on the host. Each world has its own random RCON password.
- **Secrets live in `.env`**, which is gitignored. `.env.example` documents every variable.
- **Game access control:** online mode (Microsoft account verification) plus an enforced whitelist, forced on for every world.
- **Docker socket:** the dashboard mounts `/var/run/docker.sock` to create and control world containers. That is root-equivalent on the host, which is part of why the dashboard stays local and behind a login.
- _TODO: login (argon2 hashing, sessions, CSRF), login rate limiting/lockout, audit log format._

## Setup

1. Install Docker and Docker Compose on the server.
2. Clone this repo and copy the env file:
   ```sh
   cp .env.example .env
   ```
   Fill in `FLASK_SECRET_KEY` and the admin password hash.
3. Start the dashboard:
   ```sh
   docker compose up -d --build
   ```
4. Open http://localhost:5000 on the server box and create a world. To bring in an existing world, copy its folder to `worlds/<name>/data/world` before creating a world with that name.
5. Point a playit.gg tunnel at each world's port (`localhost:25565`, `localhost:25566`, ...).

## Features

- [ ] Create / delete worlds, each as its own server container
- [ ] Edit per-world settings (version, memory, difficulty, MOTD, ...)
- [ ] Start / stop / restart each world (Docker SDK)
- [ ] Live server console/log view per world
- [ ] Online player list and whitelist management per world (RCON)
- [ ] Manual timestamped world backups
- [ ] Login with hashed passwords, sessions, CSRF protection
- [ ] Scheduled backups with retention
- [ ] Auto-restart on crash
- [ ] Container CPU/RAM stats

## Wazuh integration

_TODO: agent `localfile` config, custom decoders and rules, and screenshots of each rule firing._

Planned rules:
- Failed dashboard logins and brute-force attempts
- Non-whitelisted players trying to join (any world)
- Unexpected server stops and crash loops
- Admin actions (whitelist changes, server stops)

## Repository layout

```
docker-compose.yml   Dashboard service and the mclab network
.env.example         Dashboard config and defaults for new worlds, no real values
dashboard/           Flask app (placeholder for now)
worlds/              One directory per world (gitignored, created by the dashboard)
backups/             World backups (gitignored)
logs/                Dashboard audit log (gitignored)
```
