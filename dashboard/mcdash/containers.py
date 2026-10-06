"""World containers, controlled through the Docker SDK.

Each world runs in its own itzg/minecraft-server container named mc-<world>.
The dashboard builds the container from world.json (see worlds.container_env)
and is the only thing that creates or removes it.

Safety rules this module keeps:
- It only acts on containers labelled mc-siem-lab.world=<world>. A container
  that happens to be called mc-<world> without that label is left alone.
- The game port is published on MC_GAME_BIND_IP (127.0.0.1 by default, where
  the playit.gg agent on the same box picks it up). The RCON port is never
  published; the dashboard reaches it over the internal mclab network.
- World data is a bind mount, so removing and recreating a container never
  touches the world itself.
"""

import hashlib
import json
import os

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from .worlds import RCON_PORT, container_env

LABEL = "mc-siem-lab.world"
# Fingerprint of the settings a container was built from. If world.json has
# changed since (say a rebuild failed halfway, or the file was edited by hand),
# the next start rebuilds the container instead of running stale settings.
CONFIG_LABEL = "mc-siem-lab.config"
GAME_PORT = 25565
# Seconds Docker waits after SIGTERM before killing the server. The server
# saves the world when it gets SIGTERM; a big world needs more than Docker's
# default of 10 seconds.
STOP_TIMEOUT = 60


class ContainerError(Exception):
    pass


def container_name(world_name):
    return f"mc-{world_name}"


class WorldContainers:
    def __init__(self, client_factory, image, network, host_worlds_dir, game_bind_ip):
        self._client_factory = client_factory
        self._client = None
        self.image = image
        self.network = network
        self.host_worlds_dir = host_worlds_dir
        self.game_bind_ip = game_bind_ip

    @property
    def client(self):
        # Connect on first use, so the dashboard still starts (and the login
        # page works) when the Docker socket is missing.
        if self._client is None:
            try:
                self._client = self._client_factory()
            except DockerException as e:
                raise ContainerError(f"Cannot reach Docker: {e}") from e
        return self._client

    def get(self, world_name):
        """The world's container, or None if it hasn't been created yet."""
        try:
            container = self.client.containers.get(container_name(world_name))
        except NotFound:
            return None
        except DockerException as e:
            raise ContainerError(f"Docker error: {e}") from e
        if container.labels.get(LABEL) != world_name:
            raise ContainerError(
                f"A container named {container_name(world_name)} exists but wasn't "
                "created by this dashboard, so it won't be touched."
            )
        return container

    def status(self, world_name):
        """Docker's status ("running", "exited", ...), "not created", or "unknown"."""
        try:
            container = self.get(world_name)
        except ContainerError:
            return "unknown"
        return container.status if container is not None else "not created"

    def stats(self, world_name):
        """CPU and memory use of a running world's container, or None.

        Returns {"cpu_percent", "memory_bytes", "memory_limit_bytes"}. The
        Docker API takes about a second to answer, since it samples CPU twice.
        """
        try:
            container = self.get(world_name)
            if container is None or container.status != "running":
                return None
            raw = container.stats(stream=False)
        except (ContainerError, DockerException):
            return None
        return parse_stats(raw)

    def rcon_host(self, world_name):
        # Docker's embedded DNS resolves container names on a user network.
        return container_name(world_name), RCON_PORT

    def _kwargs(self, world):
        name = world["name"]
        host_data = os.path.join(self.host_worlds_dir, name, "data")
        kwargs = dict(
            name=container_name(name),
            environment=container_env(world),
            labels={LABEL: name},
            ports={f"{GAME_PORT}/tcp": (self.game_bind_ip, world["port"])},
            volumes={host_data: {"bind": "/data", "mode": "rw"}},
            network=self.network,
            # Comes back after a crash or a reboot, but stays down after a stop
            # from the dashboard.
            restart_policy={"Name": "unless-stopped"},
            # Lets `docker attach` reach the server console if ever needed.
            stdin_open=True,
            tty=True,
        )
        fingerprint = json.dumps([self.image, kwargs], sort_keys=True, default=str)
        kwargs["labels"][CONFIG_LABEL] = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        return kwargs

    def _is_stale(self, container, world):
        return container.labels.get(CONFIG_LABEL) != self._kwargs(world)["labels"][CONFIG_LABEL]

    def _create(self, world):
        kwargs = self._kwargs(world)
        try:
            try:
                return self.client.containers.create(self.image, **kwargs)
            except ImageNotFound:
                self.client.images.pull(self.image)
                return self.client.containers.create(self.image, **kwargs)
        except DockerException as e:
            raise ContainerError(f"Could not create the container: {e}") from e

    def start(self, world):
        container = self.get(world["name"])
        if container is not None and self._is_stale(container, world):
            self._remove(container)
            container = None
        container = container or self._create(world)
        try:
            container.start()
        except DockerException as e:
            raise ContainerError(f"Could not start: {e}") from e

    def stop(self, world):
        container = self.get(world["name"])
        if container is None:
            return
        try:
            container.stop(timeout=STOP_TIMEOUT)
        except DockerException as e:
            raise ContainerError(f"Could not stop: {e}") from e

    def restart(self, world):
        container = self.get(world["name"])
        if container is None or self._is_stale(container, world):
            self.start(world)
            return
        try:
            container.restart(timeout=STOP_TIMEOUT)
        except DockerException as e:
            raise ContainerError(f"Could not restart: {e}") from e

    def _remove(self, container):
        # stop() also covers a container stuck in a crash loop ("restarting"),
        # which Docker refuses to remove until it's stopped.
        try:
            container.stop(timeout=STOP_TIMEOUT)
            container.remove()
        except DockerException as e:
            raise ContainerError(f"Could not replace the container: {e}") from e

    def remove(self, world_name):
        """Stop and remove the world's container, if it has one. Data is a bind mount and stays."""
        container = self.get(world_name)
        if container is not None:
            self._remove(container)

    def recreate(self, world):
        """Rebuild the container from the current world.json.

        Settings are baked into a container's environment when it's created,
        so a settings change means remove + create. The world data is a bind
        mount and isn't touched. The new container is started only if the old
        one was running (or crash-looping, i.e. meant to be running).
        """
        container = self.get(world["name"])
        if container is None:
            return False
        was_running = container.status in ("running", "restarting")
        self._remove(container)
        new = self._create(world)
        if was_running:
            try:
                new.start()
            except DockerException as e:
                raise ContainerError(f"Recreated, but could not start: {e}") from e
        return was_running


def parse_stats(raw):
    """Turn one Docker stats sample into CPU % and memory, the way `docker stats` does.

    CPU % is relative to one core, so a busy server on a 4-core box can show
    up to 400%. Memory excludes the page cache (inactive_file on cgroup v2,
    total_inactive_file on v1), which the kernel can drop at any time.
    """
    try:
        cpu, pre = raw["cpu_stats"], raw["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre.get("cpu_usage", {}).get("total_usage", 0)
        system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        cores = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or []) or 1
        cpu_percent = cpu_delta / system_delta * cores * 100 if system_delta > 0 and cpu_delta > 0 else 0.0

        mem = raw["memory_stats"]
        extra = mem.get("stats", {})
        cache = extra.get("inactive_file", extra.get("total_inactive_file", 0))
        used = max(mem["usage"] - cache, 0)
        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_bytes": used,
            "memory_limit_bytes": mem.get("limit"),
        }
    except (KeyError, TypeError):
        # Partial sample, e.g. the container stopped mid-request.
        return None


def default_client_factory():
    return docker.from_env()
