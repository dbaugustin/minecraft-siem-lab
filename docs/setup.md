# Setup

The [README quick start](../README.md#quick-start) is the short version. This page has the details and the fixes for things that go wrong.

## What you need

- **Git**, to clone the repo.
- **Docker.**
  - Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the WSL 2 backend (the default).
  - Linux: Docker Engine and the Compose plugin ([install guide](https://docs.docker.com/engine/install/)). Add yourself to the `docker` group or run the commands with `sudo`.
- **Memory.** About 2 GB per running world (the default), plus about 4 GB if you also run Wazuh. 16 GB of RAM is comfortable for a couple of worlds and Wazuh.
- **Disk.** A few GB per world, more for big imported worlds and their backups.

On Windows, run the commands below in **PowerShell**. Git Bash also works for most of them, but it mangles paths that start with `/` and interactive prompts; see [Troubleshooting](#troubleshooting).

## 1. Clone the repo

```sh
git clone https://github.com/dbaugustin/minecraft-siem-lab.git
cd minecraft-siem-lab
```

On Windows, clone it somewhere under `C:\Users\<you>\` (for example `Documents`). Docker Desktop shares that folder with its containers by default.

## 2. Create `.env`

`.env` holds your settings and secrets. It's in `.gitignore`, so it never gets committed.

```powershell
Copy-Item .env.example .env      # Windows PowerShell
```
```sh
cp .env.example .env             # Linux
```

Open `.env` in any text editor and set:

**`FLASK_SECRET_KEY`**: a long random string that signs login sessions. Generate one:
```sh
docker compose run --rm dashboard python -c "import secrets; print(secrets.token_hex(32))"
```
The first time, this builds the dashboard image, which takes a minute.

**`DASHBOARD_ADMIN_PASSWORD_HASH`**: the hash of your dashboard password. The password itself is never stored.
```sh
docker compose run --rm dashboard python scripts/hash_password.py
```
Type a password of 12 or more characters twice. Paste the printed hash into `.env` **inside single quotes**, because it contains `$` signs:
```
DASHBOARD_ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

**`HOST_WORLDS_DIR`** (Windows only): the path of the repo's `worlds` folder as Docker Desktop's VM sees it. Take your clone's Windows path, swap `C:\` for `/run/desktop/mnt/host/c/` and the backslashes for slashes:
```
# clone at C:\Users\you\Documents\minecraft-siem-lab
HOST_WORLDS_DIR=/run/desktop/mnt/host/c/Users/you/Documents/minecraft-siem-lab/worlds
```
On Linux, leave it unset as long as you run `docker compose` from the repo folder. Set it to the absolute path of `worlds/` if you start compose from somewhere else (`sudo`, a systemd unit).

Why this is needed: the dashboard asks Docker to start each world with its folder mounted, and Docker needs the folder's path on the host, not inside the dashboard's container.

### Every setting

| Setting | Default | What it does |
|---|---|---|
| `FLASK_SECRET_KEY` | none, required | Signs sessions and CSRF tokens. The dashboard won't start with the placeholder. |
| `DASHBOARD_ADMIN_USER` | `admin` | Dashboard login name |
| `DASHBOARD_ADMIN_PASSWORD_HASH` | none, required | argon2 hash of the dashboard password |
| `BACKUP_INTERVAL_HOURS` | `24` | Back up each running world this often. `0` turns it off. |
| `BACKUP_RETENTION` | `10` | Keep the newest N backups per world. `0` keeps all. |
| `MC_DEFAULT_TYPE` | `SPIGOT` | Server software for new worlds: `SPIGOT`, `PAPER`, `VANILLA`, `FABRIC`, `FORGE`, `PURPUR` |
| `MC_DEFAULT_VERSION` | `LATEST` | Minecraft version for new worlds |
| `MC_DEFAULT_MEMORY` | `2G` | Memory for new worlds |
| `MC_BASE_PORT` | `25565` | Game port of the first world; later worlds take the next free port |
| `MC_IMAGE` | `itzg/minecraft-server:java25-jdk` | Server image. Keep a `-jdk` tag: Spigot is compiled on first start and needs a Java compiler. |
| `MC_GAME_BIND_IP` | `127.0.0.1` | Where game ports listen. `127.0.0.1` means only playit.gg on this PC can reach them. `0.0.0.0` also lets people on your LAN join directly. |
| `HOST_WORLDS_DIR` | `$PWD/worlds` | See above |
| `DASHBOARD_LOCKOUT_THRESHOLD` / `_WINDOW` / `_DURATION` | `5` / `900` / `900` | Lock a login after 5 failures in 15 minutes, for 15 minutes |

Each world's own settings (version, memory, port, whitelist) are changed on its page in the dashboard, not here.

## 3. Start the dashboard

```sh
docker compose up -d --build
```

Open http://localhost:5000 on the same PC and log in. The dashboard is only reachable from this PC, on purpose.

Check it's up with `docker compose ps` (the `mc-dashboard` container should say `running`) and read its log with `docker compose logs dashboard`.

## 4. Create a world

On the dashboard's home page, give the world a name and create it, then press **Start** on its page.

- **The first start of a Spigot world takes a long time.** Spigot doesn't publish ready-made server files, so the container compiles it with BuildTools first. Expect 10 to 40 minutes (about 35 on a Windows PC with Docker Desktop). The world page shows the build log until the server's own log takes over. Later starts take seconds; changing the version compiles again.
- To bring in a world you already have, see [Importing an existing world](worlds.md#importing-an-existing-world).
- Add yourself and your friends to the whitelist on the world's page. Every world enforces a whitelist and requires real Microsoft accounts.

## Let friends join (playit.gg)

The game ports only listen on this PC. playit.gg gives your friends a public address that tunnels to them, without opening ports on your router.

1. Install the playit agent from [playit.gg/download](https://playit.gg/download) and run it.
2. It shows a link to claim the agent. Open it and sign in to your playit.gg account.
3. On the playit.gg website, add a tunnel: type **Minecraft Java**, local address `127.0.0.1`, local port = the world's port (shown on its page: 25565 for the first world, 25566 for the second, ...).
4. Give your friends the address playit shows for that tunnel.

Each world needs its own tunnel. Never tunnel port 5000; the dashboard is meant to stay on your PC.

## After a reboot

- **Windows:** start Docker Desktop and wait for "Engine running". To skip this step in future, turn on *Settings > General > Start Docker Desktop when you sign in*.
- **Linux:** Docker starts with the system if its service is enabled (`sudo systemctl enable docker`).

Then everything with a restart policy comes back on its own: the dashboard, every world that was running when the PC shut down, and the Wazuh agent container. A world you stopped from the dashboard stays stopped. If the dashboard isn't up, run `docker compose up -d` in the repo folder.

Wazuh is a separate stack; see [wazuh.md](wazuh.md#after-a-reboot). The playit agent needs to be running too (it can start with Windows from its own settings).

## Updating

```sh
git pull
docker compose up -d --build
```

Your worlds, backups and `.env` aren't tracked by git, so pulling never touches them. Compare `.env.example` with your `.env` after an update in case new settings were added.

## Troubleshooting

**`error during connect` / `Cannot connect to the Docker daemon`.** Docker isn't running. Start Docker Desktop (Windows) or `sudo systemctl start docker` (Linux) and try again.

**The dashboard container keeps restarting.** Read `docker compose logs dashboard`. `Missing required config` or `FLASK_SECRET_KEY is a placeholder` means step 2 isn't done. A password hash pasted without single quotes also breaks, because compose treats the `$` parts as variables.

**The login page says the password is wrong, but it isn't.** Check the hash in `.env` is whole and in single quotes, then `docker compose up -d` to reload it. After five wrong tries the login locks for 15 minutes.

**A world fails to start with an error about a mount or path (Windows).** `HOST_WORLDS_DIR` is missing or wrong. It must end in `/worlds` and match where the repo really is.

**The Spigot build fails with `No compiler is provided in this environment`.** `MC_IMAGE` in `.env` points at an image without a JDK. Remove the line or use `itzg/minecraft-server:java25-jdk`, then press **Start** again.

**The Spigot build fails right after a new Minecraft release.** Spigot hasn't caught up yet. Set the world's version to the previous release on its page.

**A world won't start on Linux with permission errors.** The server runs as user 1000 inside the container. Fix ownership: `sudo chown -R 1000:1000 worlds/<world>/data`.

**`hash_password.py` hangs or errors in Git Bash.** Git Bash can't pass the password prompt through to Docker. Run it in PowerShell, or prefix it with `winpty`.

**Git Bash turns `/var/ossec/...` into `C:/Program Files/Git/var/ossec/...`.** Run `export MSYS_NO_PATHCONV=1` first, or use PowerShell.
