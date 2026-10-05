import json
import re

import pytest
from argon2 import PasswordHasher

from mcdash import create_app

USERNAME = "admin"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "logs" / "audit.jsonl"


@pytest.fixture
def docker_fake():
    return FakeDocker()


@pytest.fixture
def rcon_fake():
    return FakeRconServer()


@pytest.fixture
def app(audit_path, tmp_path, docker_fake, rcon_fake):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "x" * 64,
        "ADMIN_USERNAME": USERNAME,
        "ADMIN_PASSWORD_HASH": PasswordHasher().hash(PASSWORD),
        "AUDIT_LOG_PATH": str(audit_path),
        "LOCKOUT_THRESHOLD": 3,
        "WORLDS_DIR": str(tmp_path / "worlds"),
        "HOST_WORLDS_DIR": "/host/worlds",
        "BACKUP_DIR": str(tmp_path / "backups"),
        "DOCKER_CLIENT_FACTORY": lambda: docker_fake,
        "RCON_FACTORY": rcon_fake.connect,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html) or \
        re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no CSRF token on page"
    return match.group(1)


def login(client, username=USERNAME, password=PASSWORD, next_url=None):
    token = csrf_token(client)
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={
        "csrf_token": token, "username": username, "password": password,
    })


def read_audit(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---- Fakes for Docker and RCON ----

from docker.errors import NotFound  # noqa: E402


class FakeContainer:
    def __init__(self, name, image, kwargs):
        self.name = name
        self.image = image
        self.kwargs = kwargs
        self.labels = kwargs.get("labels", {})
        self.status = "created"
        self.removed = False
        self.calls = []

    def start(self):
        self.calls.append("start")
        self.status = "running"

    def stop(self, timeout=None):
        self.calls.append("stop")
        self.status = "exited"

    def restart(self, timeout=None):
        self.calls.append("restart")
        self.status = "running"

    def remove(self):
        self.calls.append("remove")
        self.removed = True


class _Containers:
    def __init__(self):
        self.by_name = {}
        self.created = []

    def get(self, name):
        c = self.by_name.get(name)
        if c is None or c.removed:
            raise NotFound(name)
        return c

    def create(self, image, **kwargs):
        c = FakeContainer(kwargs["name"], image, kwargs)
        self.by_name[c.name] = c
        self.created.append(c)
        return c


class _Images:
    def pull(self, image):
        pass


class FakeDocker:
    def __init__(self):
        self.containers = _Containers()
        self.images = _Images()


class FakeRcon:
    def __init__(self, server, host, port, password):
        self.server = server
        self.host, self.port, self.password = host, port, password

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self.server.connections.append((self.host, self.port, self.password))

    def close(self):
        pass

    def command(self, text):
        self.server.commands.append(text)
        for prefix, reply in self.server.replies.items():
            if text.startswith(prefix):
                return reply
        return ""


class FakeRconServer:
    """Records what the dashboard sends over RCON; `replies` maps a command prefix to its output."""

    def __init__(self):
        self.connections = []
        self.commands = []
        self.replies = {}

    def connect(self, host, port, password):
        return FakeRcon(self, host, port, password)


def post(client, path, data=None, page="/"):
    """POST a form with a valid CSRF token taken from `page`."""
    form = {"csrf_token": csrf_token(client, page)}
    form.update(data or {})
    return client.post(path, data=form)


@pytest.fixture
def logged_in(client):
    login(client)
    return client
