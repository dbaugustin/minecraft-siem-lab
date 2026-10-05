import pytest

from mcdash import create_app
from conftest import PASSWORD, csrf_token, login, read_audit


def test_index_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")


def test_login_success_sets_session_and_audits(client, audit_path):
    resp = login(client)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    assert client.get("/").status_code == 200

    events = read_audit(audit_path)
    assert events[-1]["event"] == "login_success"
    assert events[-1]["user"] == "admin"
    assert events[-1]["app"] == "mc-dashboard"


def test_session_cookie_flags(client):
    resp = login(client)
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


def test_wrong_password_rejected(client, audit_path):
    resp = login(client, password="wrong")
    assert resp.status_code == 401
    assert b"Invalid username or password." in resp.data
    assert client.get("/").status_code == 302

    event = read_audit(audit_path)[-1]
    assert event["event"] == "login_failure"
    assert event["reason"] == "bad_password"
    assert "password" not in {k for k in event if k != "reason"}


def test_unknown_user_gets_same_message(client, audit_path):
    resp = login(client, username="root", password="whatever")
    assert resp.status_code == 401
    assert b"Invalid username or password." in resp.data
    assert read_audit(audit_path)[-1]["reason"] == "unknown_user"


def test_unknown_user_with_admin_password_rejected(client):
    assert login(client, username="root", password=PASSWORD).status_code == 401


def test_login_without_csrf_token_rejected(client, audit_path):
    resp = client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert resp.status_code == 400
    assert client.get("/").status_code == 302
    assert read_audit(audit_path)[-1]["event"] == "csrf_failure"


def test_login_with_forged_csrf_token_rejected(client):
    resp = client.post("/login", data={
        "csrf_token": "forged", "username": "admin", "password": PASSWORD,
    })
    assert resp.status_code == 400


def test_lockout_after_threshold(client, audit_path):
    # Fixture sets LOCKOUT_THRESHOLD = 3.
    for _ in range(3):
        assert login(client, password="wrong").status_code == 401

    # Locked: even the right password is refused without being checked.
    resp = login(client)
    assert resp.status_code == 429
    assert client.get("/").status_code == 302

    events = [e["event"] for e in read_audit(audit_path)]
    assert events == ["login_failure"] * 3 + ["account_locked", "login_blocked"]


def test_success_resets_failure_count(client):
    login(client, password="wrong")
    login(client, password="wrong")
    assert login(client).status_code == 302
    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    # Counter was reset, so two more failures don't trip a threshold of 3.
    login(client, password="wrong")
    login(client, password="wrong")
    assert login(client).status_code == 302


def test_logout_requires_post_with_csrf(client, audit_path):
    login(client)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.get("/").status_code == 200

    resp = client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    assert resp.status_code == 302
    assert client.get("/").status_code == 302
    assert read_audit(audit_path)[-1]["event"] == "logout"


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/"])
def test_next_param_cannot_redirect_offsite(client, target):
    resp = login(client, next_url=target)
    assert resp.headers["Location"] == "/"


def test_next_param_allows_local_path(client):
    assert login(client, next_url="/").headers["Location"] == "/"


def test_security_headers(client):
    resp = client.get("/login")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


@pytest.mark.parametrize("overrides", [
    {"SECRET_KEY": None},
    {"SECRET_KEY": "change-me"},
    {"ADMIN_PASSWORD_HASH": None},
])
def test_app_refuses_to_start_without_real_secrets(overrides):
    config = {"SECRET_KEY": "x" * 64, "ADMIN_PASSWORD_HASH": "$argon2id$placeholder"}
    config.update(overrides)
    with pytest.raises(RuntimeError):
        create_app(config)
