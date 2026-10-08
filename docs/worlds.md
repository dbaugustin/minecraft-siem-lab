# Worlds

Each world is its own Minecraft server: a separate `itzg/minecraft-server` container named `mc-<world>`, with its own game port. You create, start, stop and configure worlds from the dashboard; nothing about them goes in `docker-compose.yml`.

## Where a world lives

```
worlds/
  survival/
    world.json        settings the dashboard edits
    data/             the server's files: world/, server.properties, logs/, ...
  creative/
    ...
```

`world.json` is the source of truth for a world's settings:

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
    "motd": "My survival world",
    "pvp": true
  },
  "whitelist": ["player1", "player2"],
  "ops": ["player1"]
}
```

**How a settings change applies.** The dashboard saves `world.json`, then recreates the world's container with matching itzg environment variables (`VERSION`, `MEMORY`, `DIFFICULTY`, `MOTD`, ...). The itzg image rewrites `server.properties` from those on every start, so editing `server.properties` by hand doesn't stick; change settings in the dashboard. The world's files in `data/` survive the recreate. Whitelist changes on a running server go through RCON and apply without a restart.

**Fixed for every world**, whatever `world.json` says: online mode on (real Microsoft accounts only), whitelist enforced, RCON on with a random per-world password and never published outside Docker, and a `mc-siem-lab.world=<name>` label so the dashboard only ever touches its own containers.

**Ports.** The first world gets `MC_BASE_PORT` (25565), each new one the next free port. Each needs its own playit.gg tunnel.

## Server software

New worlds use Spigot by default (`MC_DEFAULT_TYPE` in `.env`); each world's type can be changed on its page.

Spigot has no ready-made download, so the container builds it with BuildTools on the first start and after every version change. That takes 10 to 40 minutes and needs internet access to hub.spigotmc.org. The world page shows the build log (`data/spigot_build.log`) until the server's own log appears. The built server is kept in `data/` and reused.

Right after a new Minecraft release, `LATEST` can fail to build until Spigot catches up. Pin the previous version on the world's page if that happens.

Paper, Purpur and Vanilla download a ready-made server instead, so their first start only takes a few minutes.

## Importing an existing world

You can move a world from another server (vanilla, Paper, a hosting service, Crafty, Realms download, ...) into a new world here. Everything inside the world folder carries over: terrain, the nether and end, and each player's inventory, position, advancements and stats. The whitelist and ops don't come from the old files; add players on the world's page.

1. **Create the world** in the dashboard, for example `kingdoms`. **Don't start it yet.**
2. **Set its version** on its page to the version the old server last ran, or newer. Opening a world in an older version than it was saved with can corrupt it. `LATEST` is fine if it's at least that version.
3. **Find the old world folder.** It's the folder that contains `level.dat`. Its name was `level-name` in the old `server.properties`, usually `world`.
4. **Copy it to `worlds/kingdoms/data/world`.** It must be called `world` here, whatever it was called before. On Windows, use File Explorer: open your clone's `worlds\kingdoms\data` folder and paste it in.
   - From Spigot or Paper on 1.21 or older, there are also `world_nether` and `world_the_end` folders next to it. Copy those into `worlds/kingdoms/data/` too.
   - From vanilla 1.21 or older, the nether and end are inside the world folder (`DIM-1`, `DIM1`). Leave them there; Spigot moves them on first start.
   - From 26.1 or newer, the nether, end and player files are inside the world folder (`world/dimensions/`, `world/players/`). Leave that layout as it is.
   - Don't copy the old `server.properties`, `whitelist.json` or `ops.json`; the dashboard writes those. `usercache.json` is fine to copy into `data/`.
5. **Linux only:** give the files to the server's user: `sudo chown -R 1000:1000 worlds/kingdoms/data`.
6. **Whitelist your players**, then **start** the world. On Spigot the first start compiles the server, so give it time and watch the log on the world page. You want to see the nether and end load, and no "creating new world" message.
7. **Join and check** your base and inventory, then press **Back up now** so you have a known-good copy.

**Players start with empty inventories?** Player files are named by account UUID. Every world here runs in online mode, so a player keeps their stuff only if the old server was online mode too (the normal case). Files from an offline-mode server use different UUIDs; to carry one over, copy `playerdata/<old uuid>.dat` (or `players/data/` on 26.1+), plus the matching `advancements/` and `stats/` files, to the player's real UUID before they join. A player's real UUID is shown on namemc.com or in the server log when they first connect.

## Backups

- **Back up now** on a world's page writes `backups/<world>/<world>-<UTC time>.tar.gz` in your clone. On a running server it pauses autosave and flushes the world to disk first, so the copy is consistent.
- **Scheduled backups** run for every running world every `BACKUP_INTERVAL_HOURS` (default 24; `0` turns them off), counted from that world's newest backup, so restarting the dashboard doesn't reset the clock. Stopped worlds are skipped because their data can't change.
- **Retention:** after each backup, all but the newest `BACKUP_RETENTION` (default 10) backups of that world are deleted. `0` keeps everything.
- Backups stay on your PC; `backups/` is never committed. Copy the folder somewhere else (another drive, cloud storage) if you want protection against losing the PC.

### Restoring a backup

1. **Stop** the world in the dashboard.
2. Rename `worlds/<world>/data` to something like `data-old`.
3. Make a new empty `worlds/<world>/data` and extract the backup into it. The archive holds a `<world>/` folder, so strip that level:
   ```sh
   mkdir worlds/<world>/data
   tar -xzf backups/<world>/<file>.tar.gz -C worlds/<world>/data --strip-components=1
   ```
   `tar` is built into Windows 10 and 11, so the same commands work in PowerShell (use `mkdir` the same way).
4. **Start** the world. Once it looks right, delete `data-old`.

## Deleting a world

On the world's page, stop it, type its name and press **Delete world**. The container is removed and `worlds/<world>` moves to `worlds/.deleted/<world>-<UTC time>`; its backups stay in `backups/<world>`.

To undo, move the folder back to `worlds/<world>`; the world reappears and gets a fresh container when started. To free the disk space for good, delete the folder in `worlds/.deleted/` yourself.
