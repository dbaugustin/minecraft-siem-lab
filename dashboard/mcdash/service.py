"""World actions: what the dashboard's buttons actually do.

Views call these; each returns normally on success and raises a WorldError,
ContainerError or RconError with a message for the user on failure. Auditing
happens in the views, so a failed action never writes a success event.

Actions on one world are serialised with a per-world lock: gunicorn runs
several threads, and two overlapping "recreate" calls would race.
"""

import json
import os
import re
import tarfile
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone

from .containers import ContainerError
from .rcon import RconError
from .upload import UploadError, import_zip
from .worlds import WorldError, parse_settings, valid_player

# Minecraft's formatting codes (section sign + one character) show up in
# command output; they mean nothing in a browser.
FORMAT_CODE_RE = re.compile("\u00a7.")
CONSOLE_HISTORY = 30


class WorldBusyError(WorldError):
    """Another action on the same world holds its lock."""


class SettingsSavedError(Exception):
    """Settings were saved, but rebuilding the container failed."""

    def __init__(self, changed, cause):
        super().__init__(str(cause))
        self.changed = changed


class WorldService:
    def __init__(self, store, containers, rcon_factory, backup_dir):
        self.store = store
        self.containers = containers
        self.rcon_factory = rcon_factory
        self.backup_dir = backup_dir
        self._locks = {}
        self._locks_guard = threading.Lock()
        # Recent console commands and their output, per world. In memory
        # only: gunicorn runs a single worker, and losing it on restart is fine.
        self._console = {}

    @contextmanager
    def locked(self, name):
        with self._locks_guard:
            lock = self._locks.setdefault(name, threading.Lock())
        if not lock.acquire(timeout=5):
            raise WorldBusyError("Another action on this world is still running. Try again shortly.")
        try:
            yield
        finally:
            lock.release()

    # ---- RCON ----

    def is_running(self, name):
        return self.containers.status(name) == "running"

    def rcon(self, world):
        host, port = self.containers.rcon_host(world["name"])
        return self.rcon_factory(host, port, world["rcon_password"])

    def online_players(self, world):
        """Names of players online, or None if the server can't be asked."""
        if not self.is_running(world["name"]):
            return None
        try:
            with self.rcon(world) as rcon:
                reply = rcon.command("list")
        except RconError:
            return None
        # "There are 1 of a max of 10 players online: Steve, Alex"
        _, _, names = reply.partition(":")
        return [n.strip() for n in names.split(",") if n.strip()]

    # ---- Lifecycle ----

    def start(self, name):
        with self.locked(name):
            self.containers.start(self.store.load(name))

    def stop(self, name):
        with self.locked(name):
            self.containers.stop(self.store.load(name))

    def restart(self, name):
        with self.locked(name):
            self.containers.restart(self.store.load(name))

    # ---- Delete ----

    def delete(self, name):
        """Remove the world's container and move its folder to worlds/.deleted/.

        Nothing is erased: the folder (world.json and data/) is moved aside
        and backups are kept, so a deleted world can be restored by hand.
        A running world must be stopped first, so it gets to save.
        Returns the path the folder was moved to.
        """
        with self.locked(name):
            self.store.load(name)  # 404s on unknown names before touching Docker
            if self.containers.status(name) in ("running", "restarting"):
                raise WorldError(f"Stop {name} before deleting it.")
            self.containers.remove(name)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            return self.store.move_to_trash(name, stamp)

    # ---- Settings ----

    def update_settings(self, name, form):
        """Save new settings and rebuild the container. Returns changed keys."""
        with self.locked(name):
            world = self.store.load(name)
            other_ports = {w["port"] for w in self.store.all() if w["name"] != name}
            updated, changed = parse_settings(form, world, other_ports)
            if not changed:
                return []
            self.store.save(updated)
            try:
                self.containers.recreate(updated)
            except ContainerError as e:
                # world.json is already saved; the stale-config check in
                # containers.start() rebuilds the container on the next start.
                raise SettingsSavedError(changed, e) from e
            return changed

    # ---- Whitelist ----

    def whitelist_add(self, name, player):
        if not valid_player(player):
            raise WorldError("Player names are 3-16 letters, digits or underscores.")
        with self.locked(name):
            world = self.store.load(name)
            if player.lower() in (p.lower() for p in world["whitelist"]):
                raise WorldError(f"{player} is already on the whitelist.")
            if self.is_running(name):
                # Running: the server looks the name up with Mojang and
                # applies it immediately. It refuses names that don't exist.
                with self.rcon(world) as rcon:
                    reply = rcon.command(f"whitelist add {player}")
                if "does not exist" in reply or "Unknown" in reply:
                    raise WorldError(f"The server refused it: {reply.strip()}")
            # Stopped: the change lands in whitelist.json on next start
            # (EXISTING_WHITELIST_FILE=SYNCHRONIZE).
            world["whitelist"] = world["whitelist"] + [player]
            self.store.save(world)

    def whitelist_remove(self, name, player):
        with self.locked(name):
            world = self.store.load(name)
            match = next((p for p in world["whitelist"] if p.lower() == player.lower()), None)
            if match is None:
                raise WorldError(f"{player} is not on the whitelist.")
            if self.is_running(name):
                with self.rcon(world) as rcon:
                    rcon.command(f"whitelist remove {match}")
                    # Whitelist enforcement only checks on join; this removes
                    # them now if they're online.
                    rcon.command(f"kick {match} Removed from the whitelist")
            else:
                # itzg skips an empty WHITELIST variable, so removing the last
                # player wouldn't sync. Edit whitelist.json directly instead.
                self._drop_from_json_list(name, "whitelist.json", match)
            world["whitelist"] = [p for p in world["whitelist"] if p != match]
            # An op who can't join anymore shouldn't stay an op.
            if any(p.lower() == match.lower() for p in world["ops"]):
                self._deop(world, match)
            self.store.save(world)
            return match

    # ---- Operators ----

    def op_add(self, name, player):
        with self.locked(name):
            world = self.store.load(name)
            match = next((p for p in world["whitelist"] if p.lower() == player.lower()), None)
            if match is None:
                raise WorldError(f"{player} is not on the whitelist. Whitelist them first.")
            if any(p.lower() == match.lower() for p in world["ops"]):
                raise WorldError(f"{match} is already an operator.")
            if self.is_running(name):
                with self.rcon(world) as rcon:
                    rcon.command(f"op {match}")
            # Stopped: lands in ops.json on next start (EXISTING_OPS_FILE=SYNCHRONIZE).
            world["ops"] = world["ops"] + [match]
            self.store.save(world)
            return match

    def op_remove(self, name, player):
        with self.locked(name):
            world = self.store.load(name)
            match = self._deop(world, player)
            self.store.save(world)
            return match

    def _deop(self, world, player):
        """Take operator away from player in `world` (not saved). Returns their name."""
        match = next((p for p in world["ops"] if p.lower() == player.lower()), None)
        if match is None:
            raise WorldError(f"{player} is not an operator.")
        if self.is_running(world["name"]):
            with self.rcon(world) as rcon:
                rcon.command(f"deop {match}")
        else:
            # Same as the whitelist: itzg skips an empty OPS variable, so
            # removing the last op wouldn't sync. Edit ops.json directly.
            self._drop_from_json_list(world["name"], "ops.json", match)
        world["ops"] = [p for p in world["ops"] if p != match]
        return match

    def _drop_from_json_list(self, name, filename, player):
        path = os.path.join(self.store.data_dir(name), filename)
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        kept = [e for e in entries if e.get("name", "").lower() != player.lower()]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2)

    # ---- Console ----

    def console(self, name, command):
        """Run one console command over RCON. Returns its output, cleaned up."""
        command = command.strip()
        if command.startswith("/"):
            command = command[1:]
        if not command:
            raise WorldError("Type a command first.")
        if any(ch in command for ch in "\r\n\x00"):
            raise WorldError("Commands are one line.")
        with self.locked(name):
            world = self.store.load(name)
            if not self.is_running(name):
                raise WorldError(f"Start {name} to use the console.")
            with self.rcon(world) as rcon:
                output = FORMAT_CODE_RE.sub("", rcon.command(command)).strip()
        history = self._console.setdefault(name, deque(maxlen=CONSOLE_HISTORY))
        history.append({"command": command, "output": output})
        return command, output

    def console_history(self, name):
        return list(self._console.get(name, ()))

    # ---- Upload ----

    def upload_world(self, name, fileobj, max_bytes):
        """Import a world from a .zip into worlds/<name>/data. See upload.py.

        The server must be stopped, so it doesn't overwrite the new world
        with the old one on its next save. Returns (bytes, moved_aside).
        """
        with self.locked(name):
            self.store.load(name)
            if self.containers.status(name) in ("running", "restarting"):
                raise WorldError(f"Stop {name} before uploading a world.")
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            return import_zip(fileobj, name, self.store.data_dir(name),
                              self.store.trash_dir(), stamp, max_bytes)

    # ---- Backups ----

    def world_backup_dir(self, name):
        self.store.world_dir(name)  # validates the name
        return os.path.join(self.backup_dir, name)

    def list_backups(self, name):
        directory = self.world_backup_dir(name)
        if not os.path.isdir(directory):
            return []
        files = [f for f in os.listdir(directory) if f.endswith(".tar.gz")]
        return [
            {"file": f, "size": os.path.getsize(os.path.join(directory, f))}
            for f in sorted(files, reverse=True)
        ]

    def backup(self, name):
        """Write backups/<world>/<world>-<UTC time>.tar.gz. Returns the file name.

        On a running server, autosave is paused and the world flushed to disk
        first, so the archive isn't taken halfway through a save.
        """
        with self.locked(name):
            world = self.store.load(name)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            filename = f"{name}-{stamp}.tar.gz"
            directory = self.world_backup_dir(name)
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, filename)

            rcon = None
            if self.is_running(name):
                rcon = self.rcon(world)
                rcon.connect()
            try:
                if rcon:
                    rcon.command("save-off")
                    rcon.command("save-all flush")
                with tarfile.open(path, "w:gz") as tar:
                    tar.add(self.store.data_dir(name), arcname=name)
            except BaseException:
                if os.path.exists(path):
                    os.remove(path)
                raise
            finally:
                if rcon:
                    try:
                        rcon.command("save-on")
                    finally:
                        rcon.close()
            return filename

    def prune_backups(self, name, keep):
        """Delete all but the newest `keep` backups of a world. Returns the deleted names.

        keep <= 0 keeps everything. File names end in a sortable UTC time, so
        name order is age order.
        """
        if keep <= 0:
            return []
        directory = self.world_backup_dir(name)
        removed = []
        for backup in self.list_backups(name)[keep:]:
            os.remove(os.path.join(directory, backup["file"]))
            removed.append(backup["file"])
        return removed

    def newest_backup_time(self, name):
        """mtime of the world's newest backup, or None if it has none."""
        backups = self.list_backups(name)
        if not backups:
            return None
        return os.path.getmtime(os.path.join(self.world_backup_dir(name), backups[0]["file"]))

    # ---- Log ----

    def log_tail(self, name, lines=200):
        """Last `lines` lines of the world's latest.log, or [] if none yet.

        Before a Spigot world's first start finishes, there is no latest.log
        yet, only the BuildTools output, so show that instead.
        """
        data = self.store.data_dir(name)
        path = os.path.join(data, "logs", "latest.log")
        if not os.path.isfile(path):
            path = os.path.join(data, "spigot_build.log")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in deque(f, maxlen=lines)]


ACTION_ERRORS = (WorldError, ContainerError, RconError, UploadError, OSError)
