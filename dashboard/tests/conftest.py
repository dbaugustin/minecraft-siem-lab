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
def app(audit_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "x" * 64,
        "ADMIN_USERNAME": USERNAME,
        "ADMIN_PASSWORD_HASH": PasswordHasher().hash(PASSWORD),
        "AUDIT_LOG_PATH": str(audit_path),
        "LOCKOUT_THRESHOLD": 3,
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
