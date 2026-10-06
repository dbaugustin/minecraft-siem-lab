"""World definitions: worlds/<name>/world.json and its validation.

Each world is one Minecraft server. Its settings live in
WORLDS_DIR/<name>/world.json and its server files in WORLDS_DIR/<name>/data,
which becomes the container's /data. world.json is the single source of truth:
the container is (re)built from it, see containers.py.

Everything a form can change goes through `parse_settings`, which only accepts
known keys with checked values. That matters because these values end up as
environment variables of a container the dashboard creates through the Docker
socket.
"""

import json
import os
import re
import secrets

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
# Minecraft Java usernames: 3-16 letters, digits or underscores.
PLAYER_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
VERSION_RE = re.compile(r"^(LATEST|SNAPSHOT|\d+\.\d+(\.\d+)?)$")
MEMORY_RE = re.compile(r"^(\d+)([MG])$")

SERVER_TYPES = ("SPIGOT", "VANILLA", "PAPER", "FABRIC", "FORGE", "PURPUR")
DIFFICULTIES = ("peaceful", "easy", "normal", "hard")
GAMEMODES = ("survival", "creative", "adventure", "spectator")

MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 16 * 1024
MIN_PORT = 1024
MAX_PORT = 65535
# The RCON port inside every world container. Not published, but keep game
# ports off it anyway to avoid confusion.
RCON_PORT = 25575

# server.properties keys the dashboard lets you edit, and the itzg
# environment variable that sets each one. itzg rewrites server.properties
# from these variables on every container start.
PROPERTY_ENV = {
    "difficulty": "DIFFICULTY",
    "gamemode": "MODE",
    "max-players": "MAX_PLAYERS",
    "motd": "MOTD",
    "pvp": "PVP",
    "hardcore": "HARDCORE",
    "view-distance": "VIEW_DISTANCE",
    "spawn-protection": "SPAWN_PROTECTION",
}

DEFAULT_PROPERTIES = {
    "difficulty": "normal",
    "gamemode": "survival",
    "max-players": 10,
    "motd": "A Minecraft server",
    "pvp": True,
    "hardcore": False,
    "view-distance": 10,
    "spawn-protection": 0,
}

BOOL_PROPERTIES = ("pvp", "hardcore")
INT_PROPERTIES = {
    "max-players": (1, 100),
    "view-distance": (3, 32),
    "spawn-protection": (0, 64),
}
CHOICE_PROPERTIES = {"difficulty": DIFFICULTIES, "gamemode": GAMEMODES}
MOTD_MAX = 100


class WorldError(ValueError):
    """A request about a world that can't be carried out, with a message for the user."""


def valid_name(name):
    return bool(name and NAME_RE.match(name))


def valid_player(player):
    return bool(player and PLAYER_RE.match(player))


def memory_mb(value):
    match = MEMORY_RE.match(value or "")
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 1024 if match.group(2) == "G" else amount


class WorldStore:
    """Reads and writes world.json files under one directory."""

    def __init__(self, root):
        self.root = root

    def world_dir(self, name):
        if not valid_name(name):
            raise WorldError("Invalid world name.")
        return os.path.join(self.root, name)

    def data_dir(self, name):
        return os.path.join(self.world_dir(name), "data")

    def _json_path(self, name):
        return os.path.join(self.world_dir(name), "world.json")

    def names(self):
        if not os.path.isdir(self.root):
            return []
        return sorted(
            n for n in os.listdir(self.root)
            if valid_name(n) and os.path.isfile(os.path.join(self.root, n, "world.json"))
        )

    def exists(self, name):
        return valid_name(name) and os.path.isfile(self._json_path(name))

    def load(self, name):
        if not self.exists(name):
            raise WorldError(f"No world named {name!r}.")
        with open(self._json_path(name), encoding="utf-8") as f:
            return json.load(f)

    def all(self):
        return [self.load(n) for n in self.names()]

    def save(self, world):
        """Write world.json atomically, readable only by the dashboard's user.

        It holds the world's RCON password, hence mode 0600. Writing to a temp
        file and renaming means a crash mid-write never leaves half a file.
        """
        path = self._json_path(world["name"])
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(world, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)

    def next_free_port(self, base_port):
        used = {w["port"] for w in self.all()}
        port = base_port
        while port in used or port == RCON_PORT:
            port += 1
        return port

    def create(self, name, defaults):
        """Create worlds/<name>/world.json and data/. Returns the new world.

        `defaults` holds type, version, memory and base_port (from .env).
        An existing data/ directory is kept, which is how you import an old
        world: copy it to worlds/<name>/data/world first, then create <name>.
        """
        if not valid_name(name):
            raise WorldError(
                "World names are 1-32 characters: lowercase letters, digits, - and _, "
                "starting with a letter or digit."
            )
        if self.exists(name):
            raise WorldError(f"A world named {name!r} already exists.")
        world = {
            "name": name,
            "type": defaults["type"],
            "version": defaults["version"],
            "memory": defaults["memory"],
            "port": self.next_free_port(defaults["base_port"]),
            # 32 random bytes; only the dashboard ever needs to type it.
            "rcon_password": secrets.token_urlsafe(32),
            "properties": dict(DEFAULT_PROPERTIES, motd=f"{name} world"),
            "whitelist": [],
            "ops": [],
        }
        os.makedirs(self.data_dir(name), exist_ok=True)
        self.save(world)
        return world


def parse_settings(form, world, other_ports):
    """Validate a settings form against the current world.

    Returns (updated_world, changed_keys). Raises WorldError listing every
    problem. `other_ports` are the ports the other worlds use.
    """
    errors = []
    updated = dict(world, properties=dict(world["properties"]))

    server_type = form.get("type", "").strip().upper()
    if server_type not in SERVER_TYPES:
        errors.append("Server type must be one of " + ", ".join(SERVER_TYPES) + ".")
    updated["type"] = server_type

    version = form.get("version", "").strip().upper()
    if not VERSION_RE.match(version):
        errors.append("Version must be LATEST, SNAPSHOT or a number like 1.21.1.")
    updated["version"] = version

    memory = form.get("memory", "").strip().upper()
    mb = memory_mb(memory)
    if mb is None or not MIN_MEMORY_MB <= mb <= MAX_MEMORY_MB:
        errors.append("Memory must be between 512M and 16G, written like 2G or 1536M.")
    updated["memory"] = memory

    try:
        port = int(form.get("port", ""))
    except ValueError:
        port = None
    if port is None or not MIN_PORT <= port <= MAX_PORT or port == RCON_PORT:
        errors.append(f"Port must be a number from {MIN_PORT} to {MAX_PORT}, not {RCON_PORT}.")
    elif port in other_ports:
        errors.append(f"Port {port} is already used by another world.")
    updated["port"] = port

    props = updated["properties"]
    for key, choices in CHOICE_PROPERTIES.items():
        value = form.get(key, "").strip().lower()
        if value not in choices:
            errors.append(f"{key} must be one of " + ", ".join(choices) + ".")
        props[key] = value
    for key, (low, high) in INT_PROPERTIES.items():
        try:
            value = int(form.get(key, ""))
        except ValueError:
            value = None
        if value is None or not low <= value <= high:
            errors.append(f"{key} must be a number from {low} to {high}.")
        props[key] = value
    for key in BOOL_PROPERTIES:
        # Unchecked checkboxes aren't sent at all.
        props[key] = form.get(key) in ("on", "true", "1")

    motd = form.get("motd", "").strip()
    if not motd or len(motd) > MOTD_MAX or any(ch in motd for ch in "\r\n\x00"):
        errors.append(f"MOTD must be 1-{MOTD_MAX} characters on one line.")
    props["motd"] = motd

    if errors:
        raise WorldError(" ".join(errors))

    changed = [k for k in ("type", "version", "memory", "port") if updated[k] != world[k]]
    changed += [k for k in PROPERTY_ENV if props.get(k) != world["properties"].get(k)]
    return updated, changed


def container_env(world):
    """itzg/minecraft-server environment variables for a world.

    The hardening block at the end is fixed and does not come from world.json:
    every world gets online mode, an enforced whitelist and RCON, whatever its
    settings say.
    """
    env = {
        "EULA": "TRUE",
        "TYPE": world["type"],
        "VERSION": world["version"],
        "MEMORY": world["memory"],
    }
    if world["type"] == "SPIGOT":
        # Spigot has no official jar downloads and itzg's default source
        # (getbukkit.org) no longer allows automated downloads, so build it
        # with BuildTools. That takes several minutes on the first start and
        # after a version change; the jar is kept in /data and reused.
        env["BUILD_FROM_SOURCE"] = "TRUE"
    # itzg ignores an empty list, so only set these when there are players.
    # (Removing the last player is handled in whitelist.json directly.)
    if world["whitelist"]:
        env["WHITELIST"] = ",".join(world["whitelist"])
    if world["ops"]:
        env["OPS"] = ",".join(world["ops"])
    for key, var in PROPERTY_ENV.items():
        value = world["properties"][key]
        env[var] = str(value).lower() if isinstance(value, bool) else str(value)

    env.update({
        "ONLINE_MODE": "TRUE",
        "ENABLE_WHITELIST": "TRUE",
        "ENFORCE_WHITELIST": "TRUE",
        # world.json is the source of truth: on every start, make the server's
        # whitelist.json and ops.json match it exactly.
        "EXISTING_WHITELIST_FILE": "SYNCHRONIZE",
        "EXISTING_OPS_FILE": "SYNCHRONIZE",
        "ENABLE_RCON": "TRUE",
        "RCON_PASSWORD": world["rcon_password"],
        "RCON_PORT": str(RCON_PORT),
    })
    return env
